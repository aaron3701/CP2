import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Sample product data
products = [
    # Electronics
    {
        "name": "Wireless Earbuds",
        "price": 99.99,
        "category": "Electronics",
        "description": "Noise-cancelling earbuds with long battery life and fast charging.",
    },
    {
        "name": "Smart Watch",
        "price": 149.50,
        "category": "Electronics",
        "description": "Water-resistant smartwatch with health tracking and notifications.",
    },
    {
        "name": "Bluetooth Speaker",
        "price": 89.00,
        "category": "Electronics",
        "description": "Compact wireless speaker with rich bass and 10-hour playtime.",
    },
    {
        "name": "USB-C Power Bank",
        "price": 49.90,
        "category": "Electronics",
        "description": "10,000mAh power bank compatible with most phones and tablets.",
    },

    # Fashion
    {
        "name": "Classic Denim Jacket",
        "price": 79.90,
        "category": "Fashion",
        "description": "Stylish denim jacket perfect for casual wear.",
    },
    {
        "name": "Running Shoes",
        "price": 129.00,
        "category": "Fashion",
        "description": "Lightweight and breathable shoes designed for comfort and speed.",
    },
    {
        "name": "Leather Wallet",
        "price": 59.00,
        "category": "Fashion",
        "description": "Durable genuine leather wallet with multiple card slots.",
    },
    {
        "name": "Cotton T-Shirt",
        "price": 29.90,
        "category": "Fashion",
        "description": "Soft 100% cotton T-shirt available in various colors.",
    },

    # Groceries & Food
    {
        "name": "Organic Instant Noodles",
        "price": 6.50,
        "category": "Groceries & Food",
        "description": "Quick and healthy meal option made from natural ingredients.",
    },
    {
        "name": "Granola Cereal",
        "price": 18.90,
        "category": "Groceries & Food",
        "description": "Crunchy granola made with oats, honey, and almonds.",
    },
    {
        "name": "Bottled Green Tea",
        "price": 3.90,
        "category": "Groceries & Food",
        "description": "Refreshing sugar-free green tea with antioxidants.",
    },
    {
        "name": "Chocolate Cookies",
        "price": 7.50,
        "category": "Groceries & Food",
        "description": "Crispy chocolate chip cookies baked to perfection.",
    },

    # Home & Living
    {
        "name": "LED Desk Lamp",
        "price": 65.00,
        "category": "Home & Living",
        "description": "Adjustable lamp with touch control and eye-protection light.",
    },
    {
        "name": "Aroma Diffuser",
        "price": 45.90,
        "category": "Home & Living",
        "description": "Ultrasonic aroma diffuser that freshens up your living space.",
    },
    {
        "name": "Memory Foam Pillow",
        "price": 89.90,
        "category": "Home & Living",
        "description": "Ergonomic pillow providing superior comfort and neck support.",
    },
    {
        "name": "Non-Stick Frying Pan",
        "price": 79.00,
        "category": "Home & Living",
        "description": "Durable frying pan with heat-resistant handle and even heat distribution.",
    },

    # Health & Beauty
    {
        "name": "Vitamin C Serum",
        "price": 59.90,
        "category": "Health & Beauty",
        "description": "Brightens skin and reduces fine lines with daily use.",
    },
    {
        "name": "Herbal Shampoo",
        "price": 25.90,
        "category": "Health & Beauty",
        "description": "Natural shampoo with herbal extracts for healthy hair.",
    },
    {
        "name": "Sunscreen SPF 50+",
        "price": 39.00,
        "category": "Health & Beauty",
        "description": "Water-resistant sunscreen for long-lasting protection.",
    },
    {
        "name": "Aloe Vera Gel",
        "price": 19.50,
        "category": "Health & Beauty",
        "description": "Soothing gel for skin hydration and after-sun relief.",
    },

    # Sports & Outdoors
    {
        "name": "Yoga Mat",
        "price": 69.90,
        "category": "Sports & Outdoors",
        "description": "Eco-friendly, non-slip yoga mat with carrying strap.",
    },
    {
        "name": "Dumbbell Set",
        "price": 199.00,
        "category": "Sports & Outdoors",
        "description": "Adjustable dumbbell set suitable for home workouts.",
    },
    {
        "name": "Hiking Backpack",
        "price": 139.90,
        "category": "Sports & Outdoors",
        "description": "Waterproof backpack with multiple storage compartments.",
    },
    {
        "name": "Stainless Steel Water Bottle",
        "price": 45.00,
        "category": "Sports & Outdoors",
        "description": "Keeps drinks cold for 24 hours or hot for 12 hours.",
    },
]

# Add products to Firestore
for product in products:
    db.collection("products").add(product)
    print(f"✅ Added: {product['name']}")

print("🎉 All products added successfully!")
