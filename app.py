import os
import time
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.utils import secure_filename
import firebase_admin
from firebase_admin import credentials, firestore
import cloudinary
import cloudinary.uploader

# --- Import chatbot logic ---
import chatbot_logic

app = Flask(__name__)
app.secret_key = "supersecretkey"

# --- Initialize Firebase Admin ---
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {
    'storageBucket': 'your-project-id.appspot.com'
})
db = firestore.client()

# --- Cloudinary Configuration ---
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
    """
    try:
        file.seek(0)
        upload_result = cloudinary.uploader.upload(
            file,
            folder = "ecom_products",
            resource_type = "auto"
        )
        return upload_result.get("secure_url")
    except Exception as e:
        print(f"Error uploading file to Cloudinary: {e}")
        return None

# --- Load LLM and RAG models into memory ---
print("🔧 Building/Loading RAG…")
rag_collection = chatbot_logic.build_rag_if_missing()
print("🧠 Loading LLM…")
llm_model = chatbot_logic.load_llm() 
print("✅ Models loaded. Starting Flask app...")

# --- GLOBAL PRODUCT COLLECTION (for chromadb semantic search) ---
product_coll = None

def fetch_all_products():
    """Return list of product dicts from Firestore (includes id as 'id')."""
    prods = []
    try:
        for doc in db.collection("products").stream():
            d = doc.to_dict() or {}
            d["id"] = doc.id
            prods.append(d)
    except Exception as e:
        print("Failed to fetch products for index build:", e)
    return prods

def detect_filters_from_query(q: str):
    """Simple heuristics to detect metadata filters from user query."""
    if not q:
        return None
    ql = q.lower()
    where = {}
    if any(tok in ql for tok in ["men", "men's", "mens", "male", "for men", "for a man"]):
        where["gender"] = "male"
    elif any(tok in ql for tok in ["women", "women's", "womens", "female", "for women", "for a woman"]):
        where["gender"] = "female"
    return where or None

def get_product_recommendations(user_input, top_k=6):
    """
    Query chroma product index for semantically similar products with optional metadata filtering.
    Returns a formatted context string for the LLM.
    """
    global product_coll
    if product_coll is None:
        return ""

    # detect filters from user query
    where = detect_filters_from_query(user_input)

    # primary semantic query with filters
    results = chatbot_logic.product_index_query(product_coll, user_input, n_results=top_k, where=where)
    
    # fallback: try without filters if filtered query returned nothing
    if not results and where:
        results = chatbot_logic.product_index_query(product_coll, user_input, n_results=top_k, where=None)

    if not results:
        return ""

    # format to context for LLM
    ctx_lines = ["Product Catalog Matches:"]
    for r in results:
        meta = r.get("meta", {})
        name = meta.get("name", "Unknown")
        price = meta.get("price", "")
        category = meta.get("category", "")
        ctx_lines.append(f"- Name: {name} | Price: RM{price} | Category: {category}")
    
    return "\n".join(ctx_lines)

# Build the product index at startup
try:
    products_list = fetch_all_products()
    product_coll = chatbot_logic.build_product_index_if_missing(products_list, force_rebuild=True)
    print(f"✅ Product semantic index ready. Items indexed: {product_coll.count() if product_coll else 0}")
except Exception as e:
    print(f"❌ Failed to build product index at startup: {e}")

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

    all_unique_categories = sorted(list(set(p.get('category') for p in all_products if p.get('category'))))
    current_category = request.args.get('category', 'all')
    
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

@app.route("/profile", methods=["GET", "POST"])
def profile():
    """User profile page - allows editing username and password"""
    if "user" not in session:
        flash("Please log in first")
        return redirect(url_for("login"))
    
    if request.method == "POST":
        current_username = session.get("user")
        new_username = request.form.get("username", "").strip()
        new_password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        
        if not new_username:
            flash("Username cannot be empty", "error")
            return redirect(url_for("profile"))
        
        if new_password:
            if len(new_password) < 6:
                flash("Password must be at least 6 characters long", "error")
                return redirect(url_for("profile"))
            
            if new_password != confirm_password:
                flash("Passwords do not match", "error")
                return redirect(url_for("profile"))
        
        try:
            users_ref = db.collection("users")
            
            if new_username != current_username:
                existing_user = users_ref.where("username", "==", new_username).get()
                if existing_user:
                    flash("Username already taken", "error")
                    return redirect(url_for("profile"))
            
            current_user_docs = users_ref.where("username", "==", current_username).get()
            if not current_user_docs:
                flash("User not found", "error")
                return redirect(url_for("login"))
            
            user_doc = current_user_docs[0]
            user_id = user_doc.id
            
            update_data = {"username": new_username}
            
            if new_password:
                update_data["password"] = new_password
            
            users_ref.document(user_id).update(update_data)
            session["user"] = new_username
            
            flash("Profile updated successfully!", "success")
            return redirect(url_for("profile"))
            
        except Exception as e:
            print(f"Error updating profile: {e}")
            flash("Failed to update profile. Please try again.", "error")
            return redirect(url_for("profile"))
    
    return render_template("profile.html", username=session.get("user"))

# ------------------ Helper: Check if user is admin ------------------
def is_admin(username):
    """Check if user has admin privileges"""
    ADMIN_USERS = ["admin", "aaron"]
    return username in ADMIN_USERS

# ------------------ Admin Panel ------------------
@app.route("/admin")
def admin():
    """Admin panel for managing products - ADMIN ONLY"""
    if "user" not in session:
        flash("Please log in to access admin panel")
        return redirect(url_for("login"))
    
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
        name = request.form.get("name")
        price = request.form.get("price")
        category = request.form.get("category")
        description = request.form.get("description")
        
        try:
            price = float(price)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid price value"}), 400

        image_url = ""
        file = request.files.get("file")
        
        if file and file.filename:
            image_url = upload_file_to_cloudinary(file)
            
            if not image_url:
                return jsonify({"error": "Image upload failed via Cloudinary. Check server logs."}), 500
        
        elif request.form.get("imageUrl"):
            image_url = request.form.get("imageUrl")
        
        else:
            return jsonify({"error": "Please provide an image file or a direct URL"}), 400
        
        product_data = {
            "name": name,
            "price": price,
            "category": category,
            "description": description,
            "image": image_url
        }
        
        doc_ref = db.collection("products").add(product_data)

        # Rebuild product index after adding new product (force rebuild)
        global product_coll
        products_list = fetch_all_products()
        product_coll = chatbot_logic.build_product_index_if_missing(products_list, force_rebuild=True)

        # doc_ref may be (DocumentReference, write_time) depending on SDK — use [0].id if tuple
        product_id = doc_ref[0].id if isinstance(doc_ref, (list, tuple)) else getattr(doc_ref, "id", None)
        return jsonify({
            "message": "Product added successfully",
            "product_id": product_id
        }), 201
        
    except Exception as e:
        print(f"Error adding product: {e}")
        return jsonify({"error": "Failed to add product"}), 500

# ------------------ API: Get Single Product ------------------
@app.route("/api/products/<product_id>", methods=["GET"])
def api_get_single_product(product_id):
    """Fetches details for a single product by ID"""
    if "user" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        doc = db.collection('products').document(product_id).get()
        if not doc.exists:
            return jsonify({"error": "Product not found"}), 404
            
        product_data = doc.to_dict()
        product_data['id'] = doc.id
        
        return jsonify(product_data), 200
        
    except Exception as e:
        print(f"Error fetching product: {e}")
        return jsonify({"error": "Failed to fetch product"}), 500

# ------------------ API: Update Product ------------------
@app.route("/api/products/update/<product_id>", methods=["PUT"])
def api_update_product(product_id):
    """Update an existing product in Firestore - ADMIN ONLY"""
    if "user" not in session or not is_admin(session.get("user")):
        return jsonify({"error": "Admin privileges required"}), 403
    
    try:
        doc_ref = db.collection("products").document(product_id)
        existing_product = doc_ref.get()
        if not existing_product.exists:
            return jsonify({"error": "Product not found"}), 404
            
        existing_data = existing_product.to_dict()
        image_url = existing_data.get("image", "") 

        name = request.form.get("name")
        price = request.form.get("price")
        category = request.form.get("category")
        description = request.form.get("description")
        image_option = request.form.get("imageOption")

        try:
            price = float(price)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid price value"}), 400
        
        if image_option == 'upload':
            file = request.files.get("file") 
            if file and file.filename:
                new_image_url = upload_file_to_cloudinary(file)
                if new_image_url:
                    image_url = new_image_url
                else:
                    return jsonify({"error": "New image upload failed."}), 500

        elif image_option == 'url':
            new_image_url_input = request.form.get("imageUrl")
            if new_image_url_input and new_image_url_input.strip():
                image_url = new_image_url_input.strip()
            else:
                return jsonify({"error": "Image URL is required when URL option is selected"}), 400

        product_data = {
            "name": name,
            "price": price,
            "category": category,
            "description": description,
            "image": image_url
        }
        
        doc_ref.update(product_data)
        
        # Rebuild product index after updating product
        global product_coll
        products_list = fetch_all_products()
        product_coll = chatbot_logic.build_product_index_if_missing(products_list, force_rebuild=True)
        
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
        
        # Rebuild product index after deleting product
        global product_coll
        products_list = fetch_all_products()
        product_coll = chatbot_logic.build_product_index_if_missing(products_list)
        
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
        
        if category != 'all':
            all_products = [p for p in all_products if p.get('category') == category]
        
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
# CHATBOT API
# ==========================================================

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
        chat_ref.add({
            "role": "user",
            "text": user_message,
            "created_at": firestore.SERVER_TIMESTAMP
        })
        
        # 2. Get Product Recommendations (using chromadb semantic search)
        product_context = get_product_recommendations(user_message)
        
        # 3. Get RAG info (general knowledge)
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