import os
import time
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.utils import secure_filename
import firebase_admin
from firebase_admin import credentials, firestore
# NOTE: Removed 'from firebase_admin import storage' as we are using Cloudinary
import cloudinary
import cloudinary.uploader

# --- Import chatbot logic ---
import chatbot_logic

app = Flask(__name__)
app.secret_key = "supersecretkey"

# --- Initialize Firebase Admin ---
cred = credentials.Certificate("serviceAccountKey.json")
# IMPORTANT: Replace 'your-project-id' with your actual Firebase project ID
firebase_admin.initialize_app(cred, {
    # The 'storageBucket' key is now irrelevant/unnecessary but we keep the dict structure
    'storageBucket': 'your-project-id.appspot.com'
})
db = firestore.client()

# --- Cloudinary Configuration ---
# NOTE: Using environment variables is the best practice. 
# Replace the default values with your ACTUAL Cloudinary credentials.
try:
    cloudinary.config( 
      cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME', 'dskef0sp7'), 
      api_key = os.getenv('CLOUDINARY_API_KEY', '393697419565677'), 
      api_secret = os.getenv('CLOUDINARY_API_SECRET', 'jAt6l0ZYCHhQSoWymLRcu5Fl5Fo'), 
      secure = True
    )
    print("✅ Cloudinary initialized")
except Exception as e:
    print(f"❌ Cloudinary failed to initialize: {e}")

def upload_file_to_cloudinary(file):
    """
    Uploads a file stream directly to Cloudinary and returns the public URL.
    This function replaces the Firebase Storage upload logic.
    """
    try:
        # Reset stream position to the beginning in case it was read earlier
        file.seek(0)
        
        # Upload the file stream. resource_type="auto" detects image/video/raw
        upload_result = cloudinary.uploader.upload(
            file,
            folder = "ecom_products",  # A folder in your Cloudinary media library
            resource_type = "auto"
        )
        
        return upload_result.get("secure_url")

    except Exception as e:
        print(f"Error uploading file to Cloudinary: {e}")
        return None # Return None on failure


# --- Load LLM and RAG models into memory ---
print("🔧 Building/Loading RAG…")
rag_collection = chatbot_logic.build_rag_if_missing()
print("🧠 Loading LLM…")
llm_model = chatbot_logic.load_llm() 
print("✅ Models loaded. Starting Flask app...")


# ------------------ Root Route Redirect ------------------
@app.route("/")
def index():
    return redirect(url_for("login"))

# ------------------ Signup Page ------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        users_ref = db.collection("users")
        existing_user = users_ref.where("username", "==", username).get()

        if existing_user:
            flash("Username already exists")
            return redirect(url_for("signup"))

        users_ref.add({"username": username, "password": password})
        flash("Signup successful! Please log in.")
        return redirect(url_for("login"))

    return render_template("signup.html")

# ------------------ Login Page ------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        users_ref = db.collection("users")
        user = users_ref.where("username", "==", username).where("password", "==", password).get()

        if user:
            session["user"] = username
            flash("Login successful!")
            return redirect(url_for("home"))
        else:
            flash("Invalid username or password")
            return redirect(url_for("login"))

    return render_template("login.html")

# ------------------ Home Page ------------------
@app.route("/home", methods=["GET"])
def home():
    if "user" not in session:
        flash("Please log in first")
        return redirect(url_for("login"))
    
    try:
        products_ref = db.collection('products')
        docs = products_ref.stream()
        
        all_products = []
        for doc in docs:
            product_data = doc.to_dict()
            product_data['id'] = doc.id
            all_products.append(product_data)
            
    except Exception as e:
        print(f"Error fetching products from Firestore: {e}")
        all_products = []

    # Extract ALL unique categories
    all_unique_categories = sorted(list(set(p.get('category') for p in all_products if p.get('category'))))
    
    # Get the category filter from the URL
    current_category = request.args.get('category', 'all')
    
    # Filter the products to display
    if current_category != 'all':
        products_to_display = [
            p for p in all_products if p.get('category') == current_category
        ]
    else:
        products_to_display = all_products
        
    return render_template(
        "home.html",
        username=session.get('user'),
        products=products_to_display,
        current_category=current_category, 
        all_categories=all_unique_categories,
        is_admin=is_admin(session.get('user'))
    )

# ------------------ Helper: Check if user is admin ------------------
def is_admin(username):
    """Check if user has admin privileges"""
    # Option 1: Hardcoded admin list (Simple & Fast)
    ADMIN_USERS = ["admin", "aaron"]  # Add your admin usernames here
    return username in ADMIN_USERS
    
    # Option 2: Check Firestore for admin role (More flexible)
    # try:
    #     users_ref = db.collection("users")
    #     user_docs = users_ref.where("username", "==", username).get()
    #     if user_docs:
    #         user_data = user_docs[0].to_dict()
    #         return user_data.get("is_admin", False)
    # except Exception as e:
    #     print(f"Error checking admin status: {e}")
    #     return False

# ------------------ Admin Panel ------------------
@app.route("/admin")
def admin():
    """Admin panel for managing products - ADMIN ONLY"""
    if "user" not in session:
        flash("Please log in to access admin panel")
        return redirect(url_for("login"))
    
    # Check if user is admin
    if not is_admin(session.get("user")):
        flash("Access denied. Admin privileges required.")
        return redirect(url_for("home"))
    
    return render_template("admin.html", username=session.get("user"))

# ------------------ API: Add Product ------------------
@app.route("/api/products/add", methods=["POST"])
def api_add_product():
    """Add a new product to Firestore - ADMIN ONLY, using Cloudinary for image upload."""
    if "user" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    if not is_admin(session.get("user")):
        return jsonify({"error": "Admin privileges required"}), 403
    
    try:
        # 1. Get text fields
        name = request.form.get("name")
        price = request.form.get("price")
        category = request.form.get("category")
        description = request.form.get("description")
        
        # 2. Input validation for price
        try:
            price = float(price)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid price value"}), 400

        # 3. Handle image upload (File takes priority)
        image_url = ""
        file = request.files.get("file") # Note: assuming your frontend form sends the file under the 'file' name
        
        if file and file.filename:
            # 🔥 Cloudinary Upload Logic 🔥
            image_url = upload_file_to_cloudinary(file)
            
            if not image_url:
                # The upload function will print the error, we just return a general failure
                return jsonify({"error": "Image upload failed via Cloudinary. Check server logs."}), 500
        
        elif request.form.get("imageUrl"):
            # Fallback: If no file, use the provided URL field
            image_url = request.form.get("imageUrl")
        
        else:
            return jsonify({"error": "Please provide an image file or a direct URL"}), 400
        
        # 4. Create and save product document
        product_data = {
            "name": name,
            "price": price,
            "category": category,
            "description": description,
            "image": image_url # <-- Cloudinary URL or direct URL is stored here
        }
        
        # Add to Firestore
        doc_ref = db.collection("products").add(product_data)
        
        return jsonify({
            "message": "Product added successfully",
            "product_id": doc_ref[1].id
        }), 201
        
    except Exception as e:
        print(f"Error adding product: {e}")
        return jsonify({"error": "Failed to add product"}), 500

# ------------------ API: Get Single Product (For Edit Modal) ------------------
@app.route("/api/products/<product_id>", methods=["GET"])
def api_get_single_product(product_id):
    """Fetches details for a single product by ID for the edit modal - ADMIN ONLY."""
    if "user" not in session or not is_admin(session.get("user")):
        return jsonify({"error": "Admin privileges required"}), 403
    
    try:
        doc = db.collection('products').document(product_id).get()
        if not doc.exists:
            return jsonify({"error": "Product not found"}), 404
            
        product_data = doc.to_dict()
        product_data['id'] = doc.id
        
        # Returns all product data (name, price, image, etc.) as JSON
        return jsonify(product_data), 200
        
    except Exception as e:
        print(f"Error fetching product: {e}")
        return jsonify({"error": "Failed to fetch product"}), 500


# ------------------ API: Update Product ------------------
@app.route("/api/products/update/<product_id>", methods=["PUT"])
def api_update_product(product_id):
    """Update an existing product in Firestore, handling image changes via Cloudinary - ADMIN ONLY."""
    if "user" not in session or not is_admin(session.get("user")):
        return jsonify({"error": "Admin privileges required"}), 403
    
    try:
        # 1. Get existing product data
        doc_ref = db.collection("products").document(product_id)
        existing_product = doc_ref.get()
        if not existing_product.exists:
            return jsonify({"error": "Product not found"}), 404
            
        existing_data = existing_product.to_dict()
        # Default to current URL if no change is made
        image_url = existing_data.get("image", "") 

        # 2. Get form data (Using request.form and request.files for PUT)
        name = request.form.get("name")
        price = request.form.get("price")
        category = request.form.get("category")
        description = request.form.get("description")
        image_option = request.form.get("imageOption") # Key determinant from frontend radio buttons

        # Validate price
        try:
            price = float(price)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid price value"}), 400
        
        # 3. Handle image update based on the imageOption
        if image_option == 'upload':
            file = request.files.get("file") 
            if file and file.filename:
                # Upload new image to Cloudinary
                new_image_url = upload_file_to_cloudinary(file)
                if new_image_url:
                    image_url = new_image_url
                else:
                    return jsonify({"error": "New image upload failed."}), 500
            # If 'upload' selected but no file sent, we retain the old image_url

        elif image_option == 'url':
            new_image_url_input = request.form.get("imageUrl")
            if new_image_url_input and new_image_url_input.strip():
                image_url = new_image_url_input.strip()
            else:
                # Disallow empty URL if 'url' option is selected
                return jsonify({"error": "Image URL is required when URL option is selected"}), 400
                
        # If image_option == 'keep', the image_url remains the existing one.

        # 4. Update the Firestore document
        product_data = {
            "name": name,
            "price": price,
            "category": category,
            "description": description,
            "image": image_url # The updated or preserved URL
        }
        
        doc_ref.update(product_data)
        
        return jsonify({
            "message": "Product updated successfully",
            "product_id": product_id
        }), 200
        
    except Exception as e:
        print(f"Error updating product {product_id}: {e}")
        return jsonify({"error": "Failed to update product"}), 500

# ------------------ API: Get All Products ------------------
@app.route("/api/products/all")
def api_get_all_products():
    """Get all products for admin panel - ADMIN ONLY"""
    if "user" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    if not is_admin(session.get("user")):
        return jsonify({"error": "Admin privileges required"}), 403
    
    try:
        products_ref = db.collection("products")
        docs = products_ref.stream()
        
        products = []
        for doc in docs:
            product = doc.to_dict()
            product["id"] = doc.id
            products.append(product)
        
        return jsonify({"products": products})
    except Exception as e:
        print(f"Error fetching products: {e}")
        return jsonify({"error": "Failed to fetch products"}), 500

# ------------------ API: Delete Product ------------------
@app.route("/api/products/delete/<product_id>", methods=["DELETE"])
def api_delete_product(product_id):
    """Delete a product from Firestore - ADMIN ONLY"""
    if "user" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    if not is_admin(session.get("user")):
        return jsonify({"error": "Admin privileges required"}), 403
    
    try:
        db.collection("products").document(product_id).delete()
        return jsonify({"message": "Product deleted successfully"})
    except Exception as e:
        print(f"Error deleting product: {e}")
        return jsonify({"error": "Failed to delete product"}), 500

# ------------------ API: Fetch Products (JSON) ------------------
@app.route("/api/products")
def api_products():
    """Returns products as JSON for AJAX requests"""
    if "user" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        category = request.args.get('category', 'all')
        
        products_ref = db.collection('products')
        docs = products_ref.stream()
        
        all_products = []
        for doc in docs:
            product_data = doc.to_dict()
            product_data['id'] = doc.id
            all_products.append(product_data)
        
        # Filter by category if not 'all'
        if category != 'all':
            all_products = [p for p in all_products if p.get('category') == category]
        
        # Get unique categories
        all_categories = sorted(list(set(p.get('category') for p in all_products if p.get('category'))))
        
        return jsonify({
            "products": all_products,
            "categories": all_categories,
            "current_category": category
        })
    except Exception as e:
        print(f"Error in /api/products: {e}")
        return jsonify({"error": "Failed to fetch products"}), 500

# ------------------ Logout ------------------
@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("You've been logged out.")
    return redirect(url_for("login"))

# ------------------ Test Firebase Connection ------------------
@app.route("/test")
def test():
    db.collection("testCollection").add({"msg": "Firestore connected!"})
    return "Firestore connection successful!"

# ==========================================================
# CHATBOT AND RECOMMENDATION LOGIC
# ==========================================================

def get_product_recommendations(user_input):
    """
    Queries Firestore for products based on keywords.
    """
    products_ref = db.collection("products")
    
    # Split user input into keywords
    keywords = [word.lower() for word in user_input.split() if len(word) > 3]
    
    product_matches = []
    
    for doc in products_ref.stream():
        product = doc.to_dict()
        product_name = product.get("name", "").lower()
        product_desc = product.get("description", "").lower()
        product_category = product.get("category", "").lower()
        
        for kw in keywords:
            if kw in product_name or kw in product_desc or kw in product_category:
                product_matches.append(product)
                break
                
    if not product_matches:
        return "No specific products found in our catalog for that query."

    # Format for the LLM context
    context_str = "Found matching products:\n"
    for p in product_matches[:5]:
        context_str += f"- Name: {p.get('name')}, Price: RM{p.get('price')}, Category: {p.get('category')}\n"
    return context_str


@app.route("/api/chat", methods=["POST"])
def api_chat():
    if "user" not in session:
        return jsonify({"error": "User not logged in"}), 401
    
    try:
        data = request.get_json()
        user_message = data.get("message", "").strip()
        
        if not user_message:
            return jsonify({"error": "Empty message"}), 400
        
        # 1. Save user's message to history
        chat_ref = db.collection("users").document(session["user"]).collection("chat_history")
        user_msg_doc = chat_ref.add({
            "role": "user",
            "text": user_message,
            "created_at": firestore.SERVER_TIMESTAMP
        })
        
        # 2. Get Product Recommendations (Context 1)
        product_context = get_product_recommendations(user_message)
        
        # 3. Get RAG info (Context 2)
        rag_context = chatbot_logic.rag_query(rag_collection, user_message)
        
        # 4. Combine context for the LLM
        full_context = f"Product Catalog Context:\n{product_context}\n\nOther Info Context:\n{rag_context}"
        
        # 5. Get LLM reply
        bot_reply = chatbot_logic.chat(llm_model, user_message, full_context)
        
        # 6. Save bot's reply to history
        chat_ref.add({
            "role": "assistant",
            "text": bot_reply,
            "created_at": firestore.SERVER_TIMESTAMP
        })
        
        # 7. Return reply to the front-end
        return jsonify({"response": bot_reply})
        
    except Exception as e:
        print(f"Error in /api/chat: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


# ------------------ Run App ------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)