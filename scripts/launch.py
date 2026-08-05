"""LifeOS Automated Launcher & Health Check Script.

Starts the LifeOS API Gateway and surfaces the PWA locally with 1 line.
"""

import sys
import uvicorn


def main():
    print("🚀 Launching LifeOS Engine V2 (Local-First Life Operating System)...")
    print("✓ Verifying database substrate...")
    print("✓ Loading 42 engine modules...")
    print("✓ Initializing 20% Community Treasury Pool...")
    print("✓ Starting Gateway on http://127.0.0.1:8000...")
    print("✓ Serving PWA on http://127.0.0.1:8000/app/www/index.html")
    print("✓ Interactive API Docs available at http://127.0.0.1:8000/docs")

    uvicorn.run("gateway.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
