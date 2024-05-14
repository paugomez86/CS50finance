import os

from cs50 import SQL
from datetime import datetime
from flask import Flask, jsonify, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    try:
        rows = db.execute(
            "SELECT symbol, sum(shares) AS shares FROM transactions WHERE user_id = ? GROUP BY symbol", session["user_id"])
    except Exception as e:
        print(f"Exception: {e}")
        return apology("database query error", 400)

    # Variable to store the sum of all the user's money in stocks plus cash
    total = 0

    # List to store the portfolio. Each item will be a dict for each symbol
    symbol_list = []

    for row in rows:
        # If user doesn't have at least 1 stock of a particular symbol, this doesn't have to show up in the list so we skip the whole loop
        if row["shares"] > 0:
            # Checking the price of the current symbol
            response = lookup(row["symbol"])

            # Requesting last purchase of the given symbol
            try:
                last_purchase = db.execute(
                    "SELECT price AS last FROM transactions WHERE symbol = ? ORDER BY sqltime DESC LIMIT 1", row["symbol"])
            except Exception as e:
                print(f"Exception: {e}")
                return apology("database query error", 400)

            # Calculating percentage change
            change = calc_change(response["price"], last_purchase[0]["last"])

            # Building the dict
            dict = {
                'symbol': row["symbol"],
                'shares': row["shares"],
                'price': usd(response["price"]),
                'change': change,
                'total': usd(response["price"] * row["shares"])
            }
            symbol_list.append(dict)

            # Update total
            total += response["price"] * row["shares"]

    # Get funds and add them to the money in stocks
    funds = get_user_cash()
    total += funds

    return render_template("index.html", list=symbol_list, funds=usd(funds), total=usd(total))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    if request.method == "GET":
        funds = get_user_cash()
        return render_template("buy.html", funds=usd(funds))
    else:
        # Check symbol input is not empty
        if not request.form.get("symbol"):
            return apology("must select a symbol", 400)
        else:
            # Check symbol is valid
            symbol = request.form.get("symbol")
            quote = lookup(symbol)
            if quote is None:
                return apology("invalid symbol", 400)

        # Check shares input is not empty
        if not request.form.get("shares"):
            return apology("must provide shares value", 400)
        else:
            # Check shares is a positive integer
            try:
                shares = int(request.form.get("shares"))
            except ValueError:
                return apology("invalid shares value", 400)
            if shares <= 0:
                return apology("invalid shares value", 400)

        # Check if user have enough funds
        total = quote["price"] * shares
        if total > get_user_cash():
            return apology("insificient funds", 400)

        # Input is fine. Proceed with the transaction
        try:
            db.execute("INSERT INTO transactions (user_id, type, symbol, shares, price) VALUES (?, ?, ?, ?, ?)",
                       session["user_id"], "buy", symbol, shares, quote["price"])
            db.execute("UPDATE users SET cash = cash - ? WHERE id = ?", total, session["user_id"])
        except Exception as e:
            print(f"Exception: {e}")
            return apology("database query error", 400)

        return redirect("/")


@app.route("/look")
@login_required
def look():
    q = request.args.get("q")
    if q:
        response = lookup(q)
        if response is None:
            response = []
    else:
        response = []
    return jsonify(response)


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    # Query to show all user's transactions ordered by date. In this case, we set it in ascending order
    try:
        rows = db.execute(
            "SELECT symbol, shares, price, sqltime FROM transactions WHERE user_id = ? ORDER BY sqltime ASC", session["user_id"])
    except Exception as e:
        print(f"Exception: {e}")
        return apology("database query error", 400)

    # If query works.
    # list to store each transaction
    transactions_list = []

    # Loop throught the rows thrown by the database
    for row in rows:
        # Determine if the transaction is a sale or a purchase
        if row["shares"] < 0:
            type = "Sale"
        else:
            type = "Purchase"

        # datetime.strptime() stores date and time data in an object. It must match the format given by the database
        # Later, we can get each value using desired time formats
        time_object = datetime.strptime(row["sqltime"], "%Y-%m-%d %H:%M:%S")

        # Build the dict for the current transaction
        dict = {
            'symbol': row["symbol"],
            'shares': abs(row["shares"]),
            'type': type,
            'price': usd(row["price"]),
            'date': time_object.strftime("%d %B %Y"),
            'time': time_object.strftime("%H:%M:%S")
        }
        print(dict["date"])
        transactions_list.append(dict)

    return render_template("history.html", list=transactions_list)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 400)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 400)

        # Query database for username
        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(
            rows[0]["hash"], request.form.get("password")
        ):
            return apology("invalid username and/or password", 400)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """  """
    if request.method == "GET":
        return render_template("quote.html")
    else:
        if not request.form.get("symbol"):
            return apology("must provide a valid symbol", 400)

        # Request the quote from the API using lookup()
        """ import pdb; pdb.set_trace() # Script to debug """
        response = lookup(request.form.get("symbol"))

        if not response:
            return apology("invalid symbol", 400)

        quote = {
            'symbol': response["symbol"],
            'price': usd(response["price"])
        }

        """ This was an attempt to create a list with the last quotes requested and show them in /quote
        It should be done using a new table in the database, but in the end I found it irrelevant.

        # Dictionary to store the last quotes requested
        quotes = {}

        # If the current symbol already exists, it removes it and adds it again in order to move it to the last position
        quotes.pop(response["symbol"], None)

        # If there are 8 elements, eliminates the oldest before adding the latest
        if len(quotes) == 8:
            # iter() iterates the items and next() gives the first value thus the oldest
            quotes.pop(next(iter(quotes)))

        # Adds the latest quote.    quotes[key] = value
        quotes[response["symbol"]] = usd(response["price"]) """

        return render_template("quote.html", quote=quote)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")
    else:
        # Check if fields are provided
        if not request.form.get("username"):
            return apology("must provide username", 400)

        if not request.form.get("password"):
            return apology("must provide password", 400)

        if not request.form.get("confirmation"):
            return apology("must repeat your password", 400)

        # Check if username is already used
        if db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username")):
            return apology("this username is already in use", 400)

        # Check if password and confirmation match
        if request.form.get("password") != request.form.get("confirmation"):
            return apology("passwords don't match", 400)

        # Everything is fine, create new user
        db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", request.form.get(
            "username"), generate_password_hash(request.form.get("password")))
        flash('User created')
        return render_template("login.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "GET":
        try:
            rows = db.execute(
                "SELECT symbol, sum(shares) AS shares FROM transactions WHERE user_id = ? GROUP BY symbol", session["user_id"])
        except Exception as e:
            print(f"Exception: {e}")
            return apology("database query error", 400)

        # List to store the symbol and shares. Each item will be a dict for each symbol
        symbol_list = []

        for row in rows:
            # If user doesn't have at least 1 stock of a particular symbol, this doesn't have to show up in the list so we skip the whole loop
            if row["shares"] > 0:
                # Check the price of this symbol
                response = lookup(row["symbol"])

                # Request the price of the last purchase made for this symbol
                try:
                    last_purchase = db.execute(
                        "SELECT price AS last FROM transactions WHERE symbol = ? ORDER BY sqltime DESC LIMIT 1", row["symbol"])
                except Exception as e:
                    print(f"Exception: {e}")
                    return apology("database query error", 400)

                # Calculating the percentage change. To do so, take the selling price, substract the original value,
                # then divide the difference by the original value and finally multiply it by 100
                change = calc_change(response["price"], last_purchase[0]["last"])

                # Build the the dict for the current symbol
                dict = {
                    'symbol': row["symbol"],
                    'shares': row["shares"],
                    'price': usd(response["price"]),
                    'last': usd(last_purchase[0]["last"]),
                    'change': round(change, 2)
                }

                # Append the dict to the list. In the end, the list will contain a dict for each symbol
                symbol_list.append(dict)

        return render_template("sell.html", list=symbol_list)
    else:
        # Check symbol input is not empty
        if not request.form.get("symbol"):
            return apology("must provide a symbol", 400)
        else:
            # Check symbol is valid. If it is, store price value for later
            symbol = request.form.get("symbol")
            quote = lookup(symbol)
            if quote is None:
                return apology("invalid symbol", 400)
            else:
                price = quote["price"]

        # Check shares input is not empty
        if not request.form.get("shares"):
            return apology("must provide a shares amount", 400)

        # Check if shares is a valid positive integer.
        try:
            shares = int(request.form.get("shares"))
        except ValueError:
            return apology("invalid shares value", 400)
        if shares <= 0:
            return apology("invalid shares value", 400)

        # Check if the user has enough shares of this symbol or the user has no shares at all.
        rows = db.execute("SELECT sum(shares) AS shares FROM transactions WHERE symbol = ? AND user_id = ?",
                          request.form.get("symbol"), session["user_id"])
        if rows[0]["shares"] == "None" or rows[0]["shares"] < shares:
            return apology("you don't own enough shares", 400)

        # Everything is fine. Proceed with the transaction
        try:
            # Sell transactions will be registered in the database as negative amount of shares in order to make counts and calculations easily
            shares = -abs(shares)

            # Execute the INSERT query in transactions
            db.execute("INSERT INTO transactions (user_id, type, symbol, shares, price) VALUES (?, ?, ?, ?, ?)",
                       session["user_id"], "sell", request.form.get("symbol"), shares, price)

            # Update the user's cash calculating the total value sold (shares * price). We use the request.form.get() value because we previously set shares variable value as negative
            db.execute("UPDATE users SET cash = cash + ? WHERE id = ?",
                       int(request.form.get("shares")) * price, session["user_id"])
        except Exception as e:
            print(f"Exception: {e}")
            return apology("database query error", 400)

        # Everything went fine. The app goes back to the index
        flash("Transaction successful")
        return redirect("/")


@app.route("/profile")
@login_required
def profile():
    rows = db.execute("SELECT username, cash FROM users WHERE id = ?", session["user_id"])
    user = {
        'username': rows[0]["username"],
        'cash': rows[0]["cash"]
    }
    return render_template("/profile.html", user=user)


@app.route("/change_password", methods=["POST"])
@login_required
def change_password():
    # Check if fields are provided
    if not request.form.get("old"):
        return apology("must provide old password", 400)

    if not request.form.get("new"):
        return apology("must provide new password", 400)

    if not request.form.get("confirmation"):
        return apology("must repeat new password", 400)

    # Check if new password and confirmation match
    if request.form.get("new") != request.form.get("confirmation"):
        return apology("new passwords don't match", 400)

    # Check if old password is correct. If it's incorrect, returns apology
    rows = db.execute("SELECT hash FROM users WHERE id = ?", session["user_id"])
    if not check_password_hash(rows[0]["hash"], request.form.get("old")):
        return apology("invalid old password", 400)

    # If it's correct, get hash of the new password and update database
    hash = generate_password_hash(request.form.get("new"))
    try:
        db.execute("UPDATE users SET hash = ? WHERE id = ?", hash, session["user_id"])
    except Exception as e:
        print(f"Exception: {e}")
        return apology("database query error", 400)

    flash("Password changed")
    return redirect("/profile")


@app.route("/add_funds", methods=["POST"])
@login_required
def add_funds():
    # Checking amount is not empty
    if not request.form.get("amount"):
        return apology("must provide an amount", 400)

    # Checking amount is a valid positive number
    try:
        amount = float(request.form.get("amount"))
    except ValueError:
        return apology("invalid amount", 400)
    if amount <= 0:
        return apology("invalid amount", 400)

    try:
        db.execute("UPDATE users SET cash = cash + ? WHERE id = ?", amount, session["user_id"])
    except Exception as e:
        print(f"Exception: {e}")
        return apology("database query error", 400)

    flash("Funds added")
    return redirect("/profile")

# Helper functions


def get_user_cash():
    rows = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])
    return rows[0]["cash"]


# Percentage change. It's the percentual difference between the value of the stock when it was bought and its value when it's sold. Basically the gain/loss ratio.
# To calculate it, take the current (selling) price minus original (purchase) value, then divide the difference by the original value and multiply the total by 100.
def calc_change(current, original):
    return round((current - original) / original * 100, 2)
