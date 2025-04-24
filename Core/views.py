import csv, hashlib, io, json, traceback, logging
import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from .models import RawCsv,Key

logger = logging.getLogger(__name__)

EBAY_OAUTH_URL = 'https://api.ebay.com/identity/v1/oauth2/token'
EBAY_SEARCH_URL = 'https://api.ebay.com/buy/browse/v1/item_summary/search'
EBAY_SCOPE = 'https://api.ebay.com/oauth/api_scope'
EBAY_FEE_PERCENTAGE = 0.13
DEFAULT_SHIPPING_COST = 5.0
WALMART_FEE_PERCENTAGE = 0.13

# Cache the token to avoid frequent requests
token_cache = {'token': None, 'expires_in': 0}

def get_ebay_token():
    key = Key.objects.filter(Approved=True).first()
    EBAY_CLIENT_ID = key.Client_Id
    EBAY_CLIENT_SECRET = key.Client_Secret

    if token_cache['token']:
        return token_cache['token']
    response = requests.post(
        EBAY_OAUTH_URL,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        data={'grant_type': 'client_credentials', 'scope': EBAY_SCOPE},
        auth=(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET)
    )
    response.raise_for_status()
    result = response.json()
    token_cache['token'] = result['access_token']
    return token_cache['token']


def get_ebay_avg_price(search_term, cost):
    try:
        token = get_ebay_token()
        headers = {'Authorization': f'Bearer {token}'}
        params = {
            'q': search_term,
            'limit': 10,
            'filter': 'conditionIds:{1000|3000|4000|5000},price:[5..1000]'
        }

        response = requests.get(EBAY_SEARCH_URL, headers=headers, params=params)
        response.raise_for_status()
        items = response.json().get('itemSummaries', [])
        if not items:
            return 0.0, 0.0, 0.0, 0, '#'

        prices = [float(i['price']['value']) for i in items if 'price' in i]
        shipping_prices = [
            float(i.get('shippingOptions', [{}])[0].get('shippingCost', {}).get('value', 0.0)) for i in items
        ]
        total_volume = len(items)
        ebay_url = items[0].get('itemWebUrl', '#')

        avg_price = sum(prices) / len(prices)
        avg_shipping = sum(shipping_prices) / len(shipping_prices) if shipping_prices else 0

        estimated_profit = avg_price - avg_shipping - cost
        roi = (estimated_profit / cost) * 100 if cost else 0.0

        return (
            avg_price,
            avg_shipping,
            roi,
            total_volume,
            ebay_url
        )
    except Exception as e:
        logger.error(f"eBay fetch error for {search_term}: {e}")
        return 0.0, 0.0, 0.0, 0, '#'



def hash_item(item):
    concat = f"{item['SKU']}-{item['UPC']}-{item['Title']}-{item['Cost']}-{item.get('ActualPrice', '')}"
    return hashlib.md5(concat.encode()).hexdigest()


def process_item(item_data, platform="ebay"):
    try:
        sku = item_data.get('SKU', '')
        upc = str(item_data.get('UPC', ''))
        title = str(item_data.get('Title', ''))
        cost = float(item_data.get('Cost', 0) or 0.0)
        actual_price = float(item_data.get('ActualPrice', 0) or cost)
        search_term = upc if upc and upc.lower() not in ('nan', 'none') else title

        if platform == "walmart":
            avg_price, avg_shipping, volume, product_link = get_walmart_avg_price(search_term)
            roi = 0.0  # Optionally, implement ROI in `get_walmart_avg_price` too
        else:
            avg_price, avg_shipping, roi, volume, product_link = get_ebay_avg_price(search_term, cost)

        platform_fee_percentage = EBAY_FEE_PERCENTAGE if platform == "ebay" else WALMART_FEE_PERCENTAGE
        platform_link_key = 'ebay_link' if platform == "ebay" else 'walmart_link'

        estimated_fee = avg_price * platform_fee_percentage
        estimated_shipping = avg_shipping or DEFAULT_SHIPPING_COST
        profit = avg_price - actual_price - estimated_fee - estimated_shipping
        margin = (profit / avg_price * 100) if avg_price > 0 else 0

        return {
            'SKU': sku, 'UPC': upc, 'Title': title,
            'Cost': cost, 'ActualPrice': actual_price,
            'avg_sold_price': round(avg_price, 2),
            'estimated_fees': round(estimated_fee, 2),
            'estimated_shipping': round(estimated_shipping, 2),
            'estimated_profit': round(profit, 2),
            'profit_margin': round(margin, 2),
            'roi': round(roi, 2),
            'monthly_volume': volume,
            platform_link_key: product_link
        }

    except Exception as e:
        logger.error(f"Error processing item: {str(e)}")
        return {
            'SKU': item_data.get('SKU', ''),
            'UPC': item_data.get('UPC', ''),
            'Title': item_data.get('Title', ''),
            'Cost': item_data.get('Cost', 0),
            'ActualPrice': item_data.get('ActualPrice', 0),
            'error': str(e),
            'avg_sold_price': 0,
            'estimated_fees': 0,
            'estimated_shipping': DEFAULT_SHIPPING_COST,
            'estimated_profit': 0,
            'profit_margin': 0,
            'roi': 0,
            'monthly_volume': volume,
            'ebay_link' if platform == "ebay" else 'walmart_link': '#'
        }


def analyze(request):
    if request.method == "GET" and request.GET.get("id"):
        csv_list = list(RawCsv.objects.order_by('created_at').values_list('name', flat=True))
        return JsonResponse({"results": csv_list})

    if request.method == 'GET' and not request.GET.get('download'):
        return render(request, 'home.html')

    if request.method == 'GET' and request.GET.get('download') == 'csv':
        try:
            results = request.session.get('analysis_results')
            if not results:
                return HttpResponse("No analysis results found.", content_type="text/plain")

            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="ebay_analysis.csv"'
            writer = csv.DictWriter(response, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
            return response
        except Exception as e:
            return HttpResponse(f"Error generating CSV: {str(e)}", content_type="text/plain")

    if request.method == 'POST' and request.FILES.get('file'):
        try:
            file = request.FILES['file']
            
            # Read the file content
            try:
                content = file.read().decode('utf-8')
            except UnicodeDecodeError:
                file.seek(0)
                content = file.read().decode('latin-1')
            
            # Find the actual header row by looking for specific column names
            header_indicators = ['Style', 'Style #', 'Color', 'Size', 'UPC', 'SKU']
            lines = content.splitlines()
            header_row = None
            
            for i, line in enumerate(lines):
                if all(indicator in line for indicator in header_indicators):
                    header_row = i
                    break
            
            if header_row is None:
                return JsonResponse({'error': "Could not identify header row in CSV", 'success': False}, status=400)
            
            # Read CSV starting from the identified header row
            df = pd.read_csv(io.StringIO('\n'.join(lines[header_row:])))
            
            # Clean data: Remove rows with all NaN values and strip whitespace
            df = df.dropna(how='all')
            
            # Clean string columns - remove $ signs, commas, and convert to proper types
            for col in df.columns:
                if df[col].dtype == 'object':
                    # Replace $ and commas in price columns
                    if any(price_indicator in col.lower() for price_indicator in ['retail', 'w/s', 'cost', 'cog']):
                        df[col] = df[col].astype(str).str.replace('$', '').str.replace(',', '').str.strip()
                        # Convert to float if possible
                        try:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                        except:
                            pass
                    else:
                        # Just clean other string columns
                        df[col] = df[col].astype(str).str.strip()
                        
            # Convert column names to lowercase and strip whitespace
            df.columns = df.columns.str.strip().str.lower()
            
            # Store in session
            request.session['raw_csv'] = df.to_json(orient='split')
            request.session['file_name'] = file.name
            request.session['cached_results'] = {}
            
            return JsonResponse({'columns': list(df.columns), 'success': True})
        except Exception as e:
            logger.error(f"File upload error: {traceback.format_exc()}")
            return JsonResponse({'error': f"Error processing file: {str(e)}", 'success': False}, status=400)

    if request.method == 'POST' and request.POST.get('map_action') == 'map_columns':
        try:
            sku_col = request.POST.get('sku_col', '').lower().strip()
            upc_col = request.POST.get('upc_col', '').lower().strip()
            cost_col = request.POST.get('cost_col', '').lower().strip()
            title_col = request.POST.get('title_col', '').lower().strip()
            discount_percentage = float(request.POST.get('dis_col', 0) or 0)
            platform = request.POST.get("platform", "ebay").lower().strip()

            raw_data = request.session.get('raw_csv')
            if not raw_data:
                return JsonResponse({'error': "Session expired. Please upload your file again.", 'success': False}, status=400)

            df = pd.read_json(raw_data, orient='split')
            df['SKU'] = df[sku_col]
            df['UPC'] = df[upc_col]
            df['Title'] = df[title_col]
            df['Cost'] = pd.to_numeric(df[cost_col].replace('[\$,]', '', regex=True), errors='coerce').fillna(0)
            df['ActualPrice'] = df['Cost'] * (1 - discount_percentage / 100)

            cached_results = request.session.get('cached_results', {})
            new_cache = {}
            items = df.to_dict(orient='records')
            results = []

            def worker(item):
                item_hash = hash_item(item)
                if item_hash in cached_results:
                    return cached_results[item_hash]
                else:
                    result = process_item(item, platform)
                    new_cache[item_hash] = result
                    return result

            with ThreadPoolExecutor(max_workers=15) as executor:
                results = list(executor.map(worker, items))

            cached_results.update(new_cache)
            request.session['cached_results'] = cached_results
            request.session['analysis_results'] = results

            results.sort(key=lambda x: x.get('profit_margin', 0), reverse=True)

            instance = RawCsv.objects.filter(name=request.session.get('file_name')).last()
            if not instance:
                instance = RawCsv(name=request.session.get('file_name'))
            if platform == 'ebay':
                instance.EbayData = json.dumps(results)
            else:
                instance.WalmartData = json.dumps(results)
            instance.save()

            csv_list = list(RawCsv.objects.order_by('-created_at').values_list('name', flat=True))
            return JsonResponse({"results": csv_list})
        except Exception as e:
            logger.error(f"Analysis error: {traceback.format_exc()}")
            return JsonResponse({'error': f"Analysis error: {str(e)}", 'success': False}, status=400)

    return JsonResponse({'error': 'Invalid request'}, status=400)

import json

def getData(request):
    if request.method == "POST" and request.GET.get("name"):
        name = request.GET.get("name")
        platform = request.GET.get("platform")
        # Fetch the instance corresponding to the 'name' from RawCsv model
        instance = RawCsv.objects.filter(name=name).last()
        
        if platform == "Walmart":
            platform_data = instance.WalmartData if instance else None
        elif platform == "Ebay":
            platform_data = instance.EbayData if instance else None
        else:
            platform_data = None
            
        if platform_data:
            try:
                # Convert to Python objects first
                if isinstance(platform_data, str):
                    # Replace problematic values before parsing
                    platform_data = platform_data.replace("'", '"')  # Replace all single quotes with double quotes
                    platform_data = platform_data.replace('""', '""')  # Fix potential double quotes
                
                # Parse JSON
                data = json.loads(platform_data) if isinstance(platform_data, str) else platform_data
                
                # Process data - remove problematic fields
                if isinstance(data, list):
                    for item in data:
                        # Convert empty string values to appropriate types
                        for key in list(item.keys()):
                            if item[key] == '' or item[key] == '""':
                                # For numeric fields, use 0
                                if key in ['Cost', 'ActualPrice', 'avg_sold_price', 'estimated_fees', 
                                         'estimated_shipping', 'estimated_profit', 'profit_margin', 
                                         'roi', 'monthly_volume']:
                                    item[key] = 0
                                else:
                                    item[key] = ""  # Empty string for non-numeric fields
                
                return JsonResponse({"results": data})
            except json.JSONDecodeError:
                return JsonResponse({"error": f"Invalid JSON format in {platform} data"}, status=400)
        else:
            return JsonResponse({"error": "Data not found for the provided name and platform."}, status=404)
    
    if request.method == "GET":
        name = request.GET.get("name")
        instance = RawCsv.objects.filter(name=name).last()

    return render(request, 'analyze.html')

# alanswim@aol.com



