# VibeFlex Product Generator

Free, local-first automation that creates complete Shopify draft products from reusable recipes.

## Install

```powershell
git clone https://github.com/daa25/vibeflex-shopify-theme.git
cd vibeflex-shopify-theme\product-generator
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

## Configure

Edit `.env`:

```env
SHOPIFY_STORE=vibeflex-813.myshopify.com
SHOPIFY_ADMIN_TOKEN=shpat_xxxxxxxxx
SHOPIFY_API_VERSION=2026-07
DRY_RUN=true
```

The Shopify custom app needs `read_products` and `write_products` access.

Edit `config/recipes.json` and `data/products.csv` to control blanks, colors, sizes, pricing, artwork, and launch products.

## Preview

```powershell
python generate_products.py
```

## Create Shopify drafts

Set `DRY_RUN=false` in `.env`, then run:

```powershell
python generate_products.py
```

Products remain drafts for review. Credentials stay local because `.env` is ignored by Git.
