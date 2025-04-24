import requests
from statistics import mean
import base64
import logging

logger = logging.getLogger(__name__)

EBAY_CLIENT_ID = 'RifatRah-CsvAnaly-PRD-b0e716b3d-77f498e2'
EBAY_CLIENT_SECRET = 'PRD-0e716b3d0fab-4101-434a-b3ab-34cb'
# EBAY_CLIENT_ID = 'AlanWolk-CsvAnaly-PRD-b0e92398a-3feb6e69'
# EBAY_CLIENT_SECRET = 'PRD-0e92398a3e24-80f8-4e8e-aa4c-c150'

# EBAY_OAUTH_URL = 'https://api.sandbox.ebay.com/identity/v1/oauth2/token'
# EBAY_SEARCH_URL = 'https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search'
# EBAY_SCOPE = 'https://api.ebay.com/oauth/api_scope'

EBAY_OAUTH_URL = 'https://api.ebay.com/identity/v1/oauth2/token'
EBAY_SEARCH_URL = 'https://api.ebay.com/buy/browse/v1/item_summary/search'
EBAY_SCOPE = 'https://api.ebay.com/oauth/api_scope'

def get_ebay_token():
    """Fetch eBay OAuth2 token."""
    credentials = f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': f'Basic {encoded_credentials}'
    }

    data = {
        'grant_type': 'client_credentials',
        'scope': EBAY_SCOPE
    }

    try:
        response = requests.post(EBAY_OAUTH_URL, headers=headers, data=data)
        response.raise_for_status()
        return response.json().get('access_token')
    except Exception as e:
        logger.error(f"Error fetching eBay token: {e}")
        return None

def get_ebay_avg_price(search_term):
    """Search eBay for sold items using Browse API, return metrics."""
    token = get_ebay_token()
    if not token:
        return 0, 0, 0, "#"

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    # 1. Get SOLD items
    sold_params = {
        'q': search_term,
        'filter': 'soldItemsOnly:true',
        'limit': '50'
    }

    try:
        sold_resp = requests.get(EBAY_SEARCH_URL, headers=headers, params=sold_params)
        sold_resp.raise_for_status()
        print(sold_resp)

        sold_items = sold_resp.json().get('itemSummaries', [])
        sold_prices = [float(i['price']['value']) for i in sold_items]
        shipping_costs = [
            float(i['shippingOptions'][0]['shippingCost']['value'])
            for i in sold_items
            if i.get('shippingOptions') and i['shippingOptions'][0].get('shippingCost')
        ]
        avg_price = mean(sold_prices) if sold_prices else 0.0
        avg_shipping = mean(shipping_costs) if shipping_costs else 0.0
        volume = len(sold_items)
    except Exception as e:
        logger.warning(f"Error fetching sold data for '{search_term}': {e}")
        avg_price = avg_shipping = 0.0
        volume = 0

    # 2. Get active item for eBay URL
    try:
        active_resp = requests.get(EBAY_SEARCH_URL, headers=headers, params={'q': search_term, 'limit': '1'})
        active_resp.raise_for_status()
        items = active_resp.json().get('itemSummaries', [])
        ebay_link = items[0]['itemWebUrl'] if items else "#"
    except Exception as e:
        logger.warning(f"Error fetching active item for '{search_term}': {e}")
        ebay_link = "#"

    return avg_price, avg_shipping, volume, ebay_link

# v^1.1#i^1#r^0#f^0#p^1#I^3#t^H4sIAAAAAAAA/+VYbWwURRi+u7Y0iK1RiLVYk2MBTSS7tx+3e7eb3unRA1rSj+OuLdBo6n7M0oX9uOzscb2YmLMIiTEGFCMJEcVoNVaJAhITf5BCAw1GRQUTW8VgTFB/mCjYlPCDuLt3lGslgPQSm3h/LvPOO+88zzPvOzM7eH7e/Ed3NO+YrPFW+/bn8bzP6yUW4PPnVa2orfAtrvLgJQ7e/fll+cqBil8bIa+paS4JYNrQIfD3a6oOOdcYQTKmzhk8VCCn8xqAnCVyqVhbK0diOJc2DcsQDRXxt8QjSJjhZYKmiLBAkSKDs7ZVvxaz04ggoTBN4oCnARNkKTLM2P0QZkCLDi1etyIIiZM0igdRkugkQhxOcTSL0Qzeg/i7gQkVQ7ddMByJunA5d6xZgvXmUHkIgWnZQZBoS2x1qiPWEl/V3tkYKIkVLeqQsngrA6e3mgwJ+Lt5NQNuPg10vblURhQBhEggWphhelAudg3MHcB3pWaEkBCmCFIMiixBMeWRcrVharx1cxyORZFQ2XXlgG4pVu5WitpqCJuBaBVb7XaIlrjf+VuX4VVFVoAZQVatjG2MJRJINKnIvJXk+9AmuDWm82oOTSTjqICDEMEIlISGQnKQDQOyOFEhWlHmGTM1GbqkOKJBf7thrQQ2ajBdG4ajS7SxnTr0DjMmWw6iUj/2mobBcI+zqIVVzFh9urOuQLOF8LvNW6/A1GjLMhUhY4GpCDM7XIkiCJ9OKxIys9PNxWL69MMI0mdZaS4QyGazWJbCDHNTgMRxIrChrTUl9gGNR2xfp9YL/sqtB6CKS0UE9kiocFYubWPpt3PVBqBvQqI0Sds1XNR9OqzoTOs/DCWcA9MrolwVIrIsE+aBRIWCshgOSeWokGgxSQMODiDwOVTjzS3ASqu8CFDRzrOMBkxF4ihaJqmwDFCJYWU0yMoyKtASgxIyADgAgiCy4f9TodxuqqeAaAKrLLletjwng8m14eZcR0CR++PtmkYTiXU0afSsY5plI9eVIcKJVLdBxJs2tkRutxpuSL5JVWxlOu35yyGAU+vlE6HZgBaQZkUvJRppkDBURczNrQWmTCnBm1YuBVTVNsyKZCydbinPXl02ev9ym7gz3uU7o/6j8+mGrKCTsnOLlTMe2gH4tII5JxAmGlrAqXWDt68fjrnXRT0r3op9c51TrG2SBbaKVLhyYi5dDG4VMRNAI2Pat22sw7mBdRpbgG6fZ5ZpqCowu4lZ17OmZSxeUMFcK+wyJLjCz7HDlggFbVo0TrGz4iW6R2nvXNuSyrEVV665w2t1YPpHftTj/ogB73F8wHvU5/XijfhyYim+ZF5FV2XF3YuhYgFM4WUMKpt0+9vVBNgWkEvziulb6Dld2yo929w6kRcyn6z/67Gwp6bkjWH/k/gDU68M8yuIBSVPDnjD9Z4q4p66GpLGgyRBhHCKZnvwpdd7K4n7Kxd5/Gs36xcukm8vXPQ8k3stcDD04wd4zZST11vlqRzwempaX4x+fy53NtZ09txLW7NnqNrdnlde/3hZA/ne8ET18j/8kZGdv2//9tKB1Q/u+cgvnb7005uPdAW+632o3ffFsaO1VQd3jeysHhQON47vG35j11Nj+fNXJqr7or/t3HeXp/6dI2tHtavjv4xmf7g38009Wz/01VV6TbauanLkiu/zz+In74OD7M+JwcfH1hw4eWb3orquY9sOTzbgQyZa+8rLk4eWP1F/ZIV+oXsoWXfyqO/ryS+X7GZPjZvDE88kDtMX6/svn3r1kL5B7fSfG02/u/DDwbH1p5PoC88N978vj/bKQw/v2bHtrROJsb0LauuJy+P5XSNt2e0bPm37U97bfuL8Mc/xhqcPFNbyb2UbfMD9EQAA

# alan@cameowaterwear.com
# Parker303!