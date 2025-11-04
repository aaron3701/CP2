from flask import Flask, render_template, request, redirect, url_for, flash, session
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ✅ Initialize Firebase Admin
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

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
@app.route("/home")
def home():
    if "user" not in session:
        flash("Please log in first.")
        return redirect(url_for("login"))

    # 🧠 Fetch products from Firestore
    products_ref = db.collection("products").stream()
    products = [p.to_dict() for p in products_ref]

    return render_template("home.html", username=session["user"], products=products)

# ------------------ Fetch Product  ------------------
@app.route("/products")
def products():
    products_ref = db.collection("products").get()
    products = [doc.to_dict() for doc in products_ref]
    return render_template("products.html", products=products)



# ------------------ Logout ------------------
@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("You’ve been logged out.")
    return redirect(url_for("login"))

# ------------------ Test Firebase Connection ------------------
@app.route("/test")
def test():
    db.collection("testCollection").add({"msg": "Firebase connected!"})
    return "Firestore connection successful!"

# ------------------ Run App ------------------
if __name__ == "__main__":
    app.run(debug=True)
