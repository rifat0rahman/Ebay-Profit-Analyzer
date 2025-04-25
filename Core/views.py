import csv, hashlib, io, json, traceback, logging
import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from .models import RawCsv,Key
from django.views.decorators.csrf import csrf_exempt

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
    concat = f"{item.get('SKU', '')}-{item.get('UPC', '')}-{item.get('Title', '')}-{item.get('Cost', '')}-{item.get('ActualPrice', '')}-" \
             f"{item.get('optional_1', '')}-{item.get('optional_2', '')}-{item.get('optional_3', '')}"
    return hashlib.md5(concat.encode()).hexdigest()



def process_item(item_data, platform="ebay",col_names=None):
    try:
        sku = item_data.get('SKU', '')
        upc = str(item_data.get('UPC', '')).strip()
        title = str(item_data.get('Title', '')).strip()
        cost = float(item_data.get('Cost', 0) or 0.0)
        actual_price = float(item_data.get('ActualPrice', cost) or cost)

        # Optional fields from CSV
        optional_name_1 = col_names.get("optional_name_1", "") if col_names else ""
        optional_name_2 = col_names.get("optional_name_2", "") if col_names else ""
        optional_name_3 = col_names.get("optional_name_3", "") if col_names else ""

        optional_1 = item_data.get(optional_name_1, '')
        optional_2 = item_data.get(optional_name_2, '')
        optional_3 = item_data.get(optional_name_3, '')

        # Determine search term
        search_term = upc if upc and upc.lower() not in ('nan', 'none', '') else title

        avg_price = avg_shipping = roi = volume = product_link = 0.0

        if platform == "walmart":
            pass
        else:
            avg_price, avg_shipping, roi, volume, product_link = get_ebay_avg_price(search_term, cost)

        platform_fee_percentage = EBAY_FEE_PERCENTAGE if platform == "ebay" else WALMART_FEE_PERCENTAGE
        platform_link_key = 'ebay_link' if platform == "ebay" else 'walmart_link'

        estimated_fee = avg_price * platform_fee_percentage
        estimated_shipping = avg_shipping if avg_shipping else DEFAULT_SHIPPING_COST
        profit = avg_price - actual_price - estimated_fee - estimated_shipping
        margin = (profit / avg_price * 100) if avg_price > 0 else 0

        return {
            'SKU': sku,
            'UPC': upc,
            'Title': title,
            'Cost': round(cost, 2),
            'ActualPrice': round(actual_price, 2),
            'optional_1': optional_1,
            'optional_2': optional_2,
            'optional_3': optional_3,
            'avg_sold_price': round(avg_price, 2),
            'estimated_fees': round(estimated_fee, 2),
            'estimated_shipping': round(estimated_shipping, 2),
            'estimated_profit': round(profit, 2),
            'profit_margin': round(margin, 2),
            'roi': round(roi, 2),
            'monthly_volume': volume,
            platform_link_key: product_link,
            'optional_1_name':optional_name_1,
            'optional_2_name':optional_name_2,
            'optional_3_name':optional_name_3,
        }

    except Exception as e:
        logger.error(f"Error processing item: {traceback.format_exc()}")
        return {
            'SKU': item_data.get('SKU', ''),
            'UPC': item_data.get('UPC', ''),
            'Title': item_data.get('Title', ''),
            'Cost': item_data.get('Cost', 0),
            'ActualPrice': item_data.get('ActualPrice', 0),
            'optional_1': item_data.get('optional_1', ''),
            'optional_2': item_data.get('optional_2', ''),
            'optional_3': item_data.get('optional_3', ''),
            'error': str(e),
            'avg_sold_price': 0,
            'estimated_fees': 0,
            'estimated_shipping': DEFAULT_SHIPPING_COST,
            'estimated_profit': 0,
            'profit_margin': 0,
            'roi': 0,
            'monthly_volume': 0,
            'ebay_link' if platform == "ebay" else 'walmart_link': '#',
            'optional_1_name':optional_name_1,
            'optional_2_name':optional_name_2,
            'optional_3_name':optional_name_3,
        }

@csrf_exempt
def analyze(request):
    if request.method == "GET" and request.GET.get("id"):
        csv_list = list(RawCsv.objects.order_by('-created_at').values_list('name', flat=True))
        return JsonResponse({"results": csv_list})
    
    if request.method == "GET" and request.GET.get("delete"):

        name = request.GET.get("delete")
        instance = RawCsv.objects.filter(name=name)
        if len(instance):
            instance[0].delete()

        csv_list = list(RawCsv.objects.order_by('-created_at').values_list('name', flat=True))
        return JsonResponse({"results": csv_list})
    
    if request.method == 'GET' and not request.GET.get('download'):
        return render(request, 'home.html')
    
    if request.method == 'POST' and request.FILES.get('file'):
        try:
            file = request.FILES['file']

            try:
                content = file.read().decode('utf-8')
            except UnicodeDecodeError:
                file.seek(0)
                content = file.read().decode('latin-1')

            lines = content.splitlines()
            header_row = None
            for i, line in enumerate(lines):
                if 'UPC' in line:
                    header_row = i
                    break

            if header_row is None:
                return JsonResponse({'error': "Could not identify header row (UPC missing)", 'success': False}, status=400)

            df = pd.read_csv(io.StringIO('\n'.join(lines[header_row:])))
            df = df.dropna(how='all')

            for col in df.columns:
                if df[col].dtype == 'object':
                    if any(price_indicator in col.lower() for price_indicator in ['retail', 'w/s', 'cost', 'cog']):
                        df[col] = df[col].astype(str).str.replace('$', '').str.replace(',', '').str.strip()
                        try:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                        except:
                            pass
                    else:
                        df[col] = df[col].astype(str).str.strip()

            df.columns = df.columns.str.strip().str.lower()

            request.session['raw_csv'] = df.to_json(orient='split')
            request.session['file_name'] = file.name
            request.session['cached_results'] = {}

            return JsonResponse({'columns': list(df.columns), 'success': True})
        except Exception as e:
            logger.error(f"File upload error: {traceback.format_exc()}")
            return JsonResponse({'error': f"Error processing file: {str(e)}", 'success': False}, status=400)

    if request.method == 'POST' and request.POST.get('map_action') == 'map_columns':
        try:
            # Collect selected columns from mapping
            selected_fields = {
                'sku_col': request.POST.get('sku_col', '').lower().strip(),
                'upc_col': request.POST.get('upc_col', '').lower().strip(),
                'cost_col': request.POST.get('cost_col', '').lower().strip(),
                'title_col': request.POST.get('title_col', '').lower().strip(),
                'dis_col': request.POST.get('dis_col', '').strip(),  # discount %
                'optional_1': request.POST.get('optional_1', '').lower().strip(),
                'optional_2': request.POST.get('optional_2', '').lower().strip(),
                'optional_3': request.POST.get('optional_3', '').lower().strip(),
            }
            platform = request.POST.get("platform", "ebay").lower().strip()
            discount_percentage = float(selected_fields.get('dis_col') or 0)

            raw_data = request.session.get('raw_csv')
            if not raw_data:
                return JsonResponse({'error': "Session expired. Please upload your file again.", 'success': False}, status=400)

            df = pd.read_json(raw_data, orient='split')

            # UPC is required
            df['UPC'] = df[selected_fields['upc_col']]

            # Optional mappings if provided
            if selected_fields['sku_col']:
                df['SKU'] = df[selected_fields['sku_col']]

            if selected_fields['title_col']:
                df['Title'] = df[selected_fields['title_col']]

            if selected_fields['cost_col']:
                df['Cost'] = pd.to_numeric(df[selected_fields['cost_col']].replace('[\$,]', '', regex=True), errors='coerce').fillna(0)
            else:
                df['Cost'] = 0

            df['ActualPrice'] = df['Cost'] * (1 - discount_percentage / 100)

            # Optional extra columns
            optional_keys = ['optional_1', 'optional_2', 'optional_3']
            col_names = {
                "optional_name_1":"",
                "optional_name_2":"",
                "optional_name_3":"",
            }
            # Loop over the optional keys and update the col_names dictionary with the corresponding column names from selected_fields
            for idx, opt in enumerate(optional_keys):
                col_name = selected_fields.get(opt)

                if col_name:
                    col_names[f"optional_name_{idx + 1}"] = col_name
                    df[col_name] = df[col_name]
            

            cached_results = request.session.get('cached_results', {})
            new_cache = {}
            items = df.to_dict(orient='records')
        
            results = []

            def worker(item):
                item_hash = hash_item(item)
                if item_hash in cached_results:
                    return cached_results[item_hash]
                else:
                    result = process_item(item, platform,col_names=col_names)
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
from django.http import JsonResponse
from django.shortcuts import render
from .models import RawCsv  # adjust import if needed

import json
from django.http import JsonResponse
from django.shortcuts import render
from .models import RawCsv  # adjust import if needed

@csrf_exempt
def getData(request):
    if request.method == "POST" and request.GET.get("name"):
        name = request.GET.get("name")
        platform = request.GET.get("platform")
        instance = RawCsv.objects.filter(name=name).last()

        if platform == "Walmart":
            platform_data = instance.WalmartData if instance else None
        elif platform == "Ebay":
            platform_data = instance.EbayData if instance else None
        else:
            platform_data = None

        if platform_data:
            try:
                if isinstance(platform_data, str):
                    platform_data = platform_data.replace("'", '"')  # Normalize JSON quotes

                data = json.loads(platform_data) if isinstance(platform_data, str) else platform_data

                if isinstance(data, list):
                    for item in data:
                        # Ensure optional fields are always present
                        item.setdefault("optional_1", "")
                        item.setdefault("optional_2", "")
                        item.setdefault("optional_3", "")

                        # Clean up empty values
                        for key in list(item.keys()):
                            if item[key] == '' or item[key] == '""':
                                if key in ['Cost', 'ActualPrice', 'avg_sold_price', 'estimated_fees',
                                           'estimated_shipping', 'estimated_profit', 'profit_margin',
                                           'roi', 'monthly_volume']:
                                    item[key] = 0
                                else:
                                    item[key] = ""

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



