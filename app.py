from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = "super_secret_key" 

# Database connection details
DB_HOST = "localhost"
DB_NAME = "airline_db"
DB_USER = "postgres"
DB_PASS = "db_root"

def get_db_connection():
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)

# --- HOME & ADVANCED SEARCH ---
@app.route('/', methods=['GET', 'POST'])
def index():
    user_cards = []
    if 'email' in session:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT card_number FROM credit_card WHERE email = %s", (session['email'],))
        user_cards = cursor.fetchall()
        cursor.close()
        conn.close()

    if request.method == 'POST':
        dep = request.form['departure_airport']
        dest = request.form['destination_airport']
        date = request.form['flight_date']
        
        max_conns = int(request.form.get('max_connections', 0))
        max_price = float(request.form.get('max_price') or 99999.00)
        sort_by = request.form.get('sort_by', 'price') 

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        query_direct = """
            SELECT 
                f.airline_code as a1, f.flight_number as f1, f.departure_time as dep1, f.arrival_time as arr1,
                NULL as a2, NULL as f2, NULL as dep2, NULL as arr2,
                pe.amount AS economy_price, pf.amount AS first_class_price,
                (f.arrival_time - f.departure_time) AS total_length
            FROM flight f
            LEFT JOIN price pe ON f.airline_code = pe.airline_code AND f.flight_number = pe.flight_number AND f.flight_date = pe.flight_date AND pe.seat_class = 'E'
            LEFT JOIN price pf ON f.airline_code = pf.airline_code AND f.flight_number = pf.flight_number AND f.flight_date = pf.flight_date AND pf.seat_class = 'F'
            WHERE f.departure_airport = %s AND f.destination_airport = %s AND f.flight_date = %s
              AND pe.amount <= %s
        """
        
        query_1stop = """
            SELECT 
                f1.airline_code as a1, f1.flight_number as f1, f1.departure_time as dep1, f1.arrival_time as arr1,
                f2.airline_code as a2, f2.flight_number as f2, f2.departure_time as dep2, f2.arrival_time as arr2,
                (pe1.amount + pe2.amount) AS economy_price, 
                (pf1.amount + pf2.amount) AS first_class_price,
                (f2.arrival_time - f1.departure_time) AS total_length
            FROM flight f1
            JOIN flight f2 ON f1.destination_airport = f2.departure_airport AND f1.flight_date = f2.flight_date
            LEFT JOIN price pe1 ON f1.airline_code = pe1.airline_code AND f1.flight_number = pe1.flight_number AND f1.flight_date = pe1.flight_date AND pe1.seat_class = 'E'
            LEFT JOIN price pf1 ON f1.airline_code = pf1.airline_code AND f1.flight_number = pf1.flight_number AND f1.flight_date = pf1.flight_date AND pf1.seat_class = 'F'
            LEFT JOIN price pe2 ON f2.airline_code = pe2.airline_code AND f2.flight_number = pe2.flight_number AND f2.flight_date = pe2.flight_date AND pe2.seat_class = 'E'
            LEFT JOIN price pf2 ON f2.airline_code = pf2.airline_code AND f2.flight_number = pf2.flight_number AND f2.flight_date = pf2.flight_date AND pf2.seat_class = 'F'
            WHERE f1.departure_airport = %s AND f2.destination_airport = %s AND f1.flight_date = %s
              AND f2.departure_time >= f1.arrival_time + interval '30 minutes'
              AND (pe1.amount + pe2.amount) <= %s
        """

        flights = []
        if max_conns >= 0:
            cursor.execute(query_direct, (dep, dest, date, max_price))
            flights.extend(cursor.fetchall())
        if max_conns >= 1:
            cursor.execute(query_1stop, (dep, dest, date, max_price))
            flights.extend(cursor.fetchall())

        if sort_by == 'price':
            flights.sort(key=lambda x: x['economy_price'] or 99999)
        else:
            flights.sort(key=lambda x: x['total_length'])

        cursor.close()
        conn.close()
        
        return render_template('index.html', flights=flights, search_performed=True, search_date=date, user_cards=user_cards)

    return render_template('index.html', user_cards=user_cards)


# --- LOGIN & LOGOUT ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT password, first_name FROM customer WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['email'] = email
            session['name'] = user['first_name']
            flash(f"Welcome back, {user['first_name']}!", "success")
            return redirect(url_for('index'))
        else:
            flash("Invalid email or password.", "error")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for('index'))


# --- REGISTRATION ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        home_airport = request.form['home_airport']
        password = generate_password_hash(request.form['password'])

        street = request.form['street']
        city = request.form['city']
        state = request.form['state']
        zip_code = request.form['zip_code']

        card_numbers = request.form.getlist('card_number')
        holder_names = request.form.getlist('holder_name')
        expiry_dates = request.form.getlist('expiry_date')

        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("INSERT INTO customer (email, first_name, last_name, home_airport, password) VALUES (%s, %s, %s, %s, %s)",
                (email, first_name, last_name, home_airport, password))

            cursor.execute("INSERT INTO address (street, city, state, zip_code) VALUES (%s, %s, %s, %s) RETURNING address_id",
                (street, city, state, zip_code))
            address_id = cursor.fetchone()[0]

            cursor.execute("INSERT INTO customer_address (email, address_id) VALUES (%s, %s)", (email, address_id))

            for i in range(len(card_numbers)):
                if card_numbers[i].strip():
                    cursor.execute("INSERT INTO credit_card (card_number, holder_name, expiry_date, email, billing_address_id) VALUES (%s, %s, %s, %s, %s)",
                        (card_numbers[i], holder_names[i], expiry_dates[i], email, address_id))

            conn.commit()
            flash("Registration successful! You can now log in.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            conn.rollback()
            flash(f"Error during registration: {e}", "error")
        finally:
            cursor.close()
            conn.close()
            
    return render_template('register.html')


# --- PROFILE / MANAGE ---
@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'email' not in session:
        flash("Please log in to view your profile.", "error")
        return redirect(url_for('login'))
        
    email = session['email']
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    if request.method == 'POST':
        action = request.form.get('action')
        try:
            # -- DELETE ACTIONS --
            if action == 'delete_card':
                cursor.execute("DELETE FROM credit_card WHERE card_number = %s AND email = %s", (request.form['card_number'], email))
                conn.commit()
                flash("Credit card deleted.", "success")
                
            elif action == 'delete_address':
                addr_id = request.form['address_id']
                cursor.execute("DELETE FROM customer_address WHERE address_id = %s AND email = %s", (addr_id, email))
                cursor.execute("DELETE FROM address WHERE address_id = %s", (addr_id,))
                conn.commit()
                flash("Address deleted.", "success")
                
            elif action == 'cancel_booking':
                book_id = request.form['booking_id']
                cursor.execute("DELETE FROM booking_flight WHERE booking_id = %s", (book_id,))
                cursor.execute("DELETE FROM booking WHERE booking_id = %s AND email = %s", (book_id, email))
                conn.commit()
                flash("Booking canceled successfully.", "success")

            # -- EDIT ACTIONS --
            elif action == 'edit_card':
                c_num = request.form['card_number']
                h_name = request.form['holder_name']
                exp = request.form['expiry_date']
                cursor.execute("UPDATE credit_card SET holder_name = %s, expiry_date = %s WHERE card_number = %s AND email = %s", 
                               (h_name, exp, c_num, email))
                conn.commit()
                flash("Credit card updated successfully.", "success")

            elif action == 'edit_address':
                a_id = request.form['address_id']
                street = request.form['street']
                city = request.form['city']
                state = request.form['state']
                zip_code = request.form['zip_code']
                
                cursor.execute("SELECT 1 FROM customer_address WHERE address_id = %s AND email = %s", (a_id, email))
                if cursor.fetchone():
                    cursor.execute("UPDATE address SET street = %s, city = %s, state = %s, zip_code = %s WHERE address_id = %s", 
                                   (street, city, state, zip_code, a_id))
                    conn.commit()
                    flash("Address updated successfully.", "success")
                else:
                    flash("Unauthorized to edit this address.", "error")

            # -- ADD ACTIONS --
            elif action == 'add_card':
                c_num = request.form['new_card_number']
                h_name = request.form['new_holder_name']
                exp = request.form['new_expiry_date']
                b_addr_id = request.form['billing_address_id']
                
                cursor.execute("INSERT INTO credit_card (card_number, holder_name, expiry_date, email, billing_address_id) VALUES (%s, %s, %s, %s, %s)",
                               (c_num, h_name, exp, email, b_addr_id))
                conn.commit()
                flash("New credit card added successfully.", "success")
                
        except psycopg2.IntegrityError as e:
            conn.rollback()
            error_msg = str(e).lower()
            if "already exists" in error_msg or "unique constraint" in error_msg:
                flash("This credit card is already registered.", "error")
            else:
                flash("Database constraint error: Cannot delete an address that a credit card is using for billing.", "error")
        except Exception as e:
            conn.rollback()
            flash(f"An error occurred: {e}", "error")

    # Fetch User Data
    cursor.execute("SELECT * FROM credit_card WHERE email = %s", (email,))
    cards = cursor.fetchall()
    
    cursor.execute("SELECT a.address_id, a.street, a.city, a.state, a.zip_code FROM address a JOIN customer_address ca ON a.address_id = ca.address_id WHERE ca.email = %s", (email,))
    addresses = cursor.fetchall()
    
    cursor.execute("""
        SELECT b.booking_id, b.total_price, bf.airline_code, bf.flight_number, bf.flight_date, bf.seat_class
        FROM booking b JOIN booking_flight bf ON b.booking_id = bf.booking_id WHERE b.email = %s
    """, (email,))
    bookings = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template('profile.html', cards=cards, addresses=addresses, bookings=bookings)


# --- BOOKING ---
@app.route('/book', methods=['POST'])
def book():
    email = session.get('email') or request.form['email']
    card_number = request.form['card_number']
    seat_class = request.form['seat_class']
    flight_date = request.form['flight_date']
    
    a1, f1 = request.form.get('a1'), request.form.get('f1')
    a2, f2 = request.form.get('a2'), request.form.get('f2')
    
    price = request.form['economy_price'] if seat_class == 'E' else request.form['first_class_price']

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO booking (email, card_number, total_price) VALUES (%s, %s, %s) RETURNING booking_id",
            (email, card_number, price))
        booking_id = cursor.fetchone()[0]

        cursor.execute("INSERT INTO booking_flight (booking_id, airline_code, flight_number, flight_date, seat_class) VALUES (%s, %s, %s, %s, %s)",
            (booking_id, a1, f1, flight_date, seat_class))
        
        if a2 and f2 and a2 != 'None':
            cursor.execute("INSERT INTO booking_flight (booking_id, airline_code, flight_number, flight_date, seat_class) VALUES (%s, %s, %s, %s, %s)",
                (booking_id, a2, f2, flight_date, seat_class))

        conn.commit()
        flash("Booking successfully completed!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Booking failed: {e}", "error")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=5001)