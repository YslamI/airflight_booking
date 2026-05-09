from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = "super_secret_key" # Needed for flash messages

# Database connection details
DB_HOST = "localhost"
DB_NAME = "airline_db"
DB_USER = "postgres"
DB_PASS = "db_root"

def get_db_connection():
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    return conn

@app.route('/')
def index():
    return render_template('index.html')

# --- 4.3 SEARCH FLIGHTS ---
@app.route('/search', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        dep_airport = request.form['departure_airport']
        dest_airport = request.form['destination_airport']
        flight_date = request.form['flight_date']
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            SELECT 
                f.airline_code, f.flight_number, f.flight_date, f.departure_time, f.arrival_time,
                pe.amount AS economy_price, pf.amount AS first_class_price,
                (f.arrival_time - f.departure_time) AS flight_length
            FROM flight f
            LEFT JOIN price pe ON f.airline_code = pe.airline_code AND f.flight_number = pe.flight_number AND f.flight_date = pe.flight_date AND pe.seat_class = 'E'
            LEFT JOIN price pf ON f.airline_code = pf.airline_code AND f.flight_number = pf.flight_number AND f.flight_date = pf.flight_date AND pf.seat_class = 'F'
            WHERE f.departure_airport = %s AND f.destination_airport = %s AND f.flight_date = %s;
        """
        cursor.execute(query, (dep_airport, dest_airport, flight_date))
        flights = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('index.html', flights=flights, search_performed=True)
    return render_template('index.html')

# --- 4.1 & 4.2 REGISTRATION WITH PAYMENT ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # 1. Customer Info
        email = request.form['email']
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        home_airport = request.form['home_airport']
        password = generate_password_hash(request.form['password']) # Secure hashing!

        # 2. Billing Address Info
        street = request.form['street']
        city = request.form['city']
        state = request.form['state']
        zip_code = request.form['zip_code']

        # 3. Credit Card Info (Using .getlist() to grab multiple inputs if the user added more)
        card_numbers = request.form.getlist('card_number')
        holder_names = request.form.getlist('holder_name')
        expiry_dates = request.form.getlist('expiry_date')

        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Step A: Insert Customer
            cursor.execute(
                "INSERT INTO customer (email, first_name, last_name, home_airport, password) VALUES (%s, %s, %s, %s, %s)",
                (email, first_name, last_name, home_airport, password)
            )

            # Step B: Insert Address and get the generated address_id
            cursor.execute(
                "INSERT INTO address (street, city, state, zip_code) VALUES (%s, %s, %s, %s) RETURNING address_id",
                (street, city, state, zip_code)
            )
            address_id = cursor.fetchone()[0]

            # Step C: Link Customer to Address in the junction table
            cursor.execute(
                "INSERT INTO customer_address (email, address_id) VALUES (%s, %s)",
                (email, address_id)
            )

            # Step D: Loop through all submitted cards and insert them
            for i in range(len(card_numbers)):
                if card_numbers[i].strip(): # Only insert if they didn't leave it blank
                    cursor.execute(
                        "INSERT INTO credit_card (card_number, holder_name, expiry_date, email, billing_address_id) VALUES (%s, %s, %s, %s, %s)",
                        (card_numbers[i], holder_names[i], expiry_dates[i], email, address_id)
                    )

            # Commit the whole transaction!
            conn.commit()
            flash("Registration successful! Your profile and payment methods are saved.", "success")
            
        except Exception as e:
            conn.rollback() # If anything fails, undo all the inserts to keep data clean
            flash(f"Error during registration: {e}", "error")
            
        finally:
            cursor.close()
            conn.close()
            
        return redirect(url_for('register'))
        
    return render_template('register.html')

# --- 4.4 BOOK FLIGHT ---
@app.route('/book', methods=['POST'])
def book():
    email = request.form['email']
    card_number = request.form['card_number']
    airline_code = request.form['airline_code']
    flight_number = request.form['flight_number']
    flight_date = request.form['flight_date']
    seat_class = request.form['seat_class']
    price = request.form['price']

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1. Create the booking record
        cursor.execute(
            "INSERT INTO booking (email, card_number, total_price) VALUES (%s, %s, %s) RETURNING booking_id",
            (email, card_number, price)
        )
        booking_id = cursor.fetchone()[0]

        # 2. Link the specific flight to the booking
        cursor.execute(
            "INSERT INTO booking_flight (booking_id, airline_code, flight_number, flight_date, seat_class) VALUES (%s, %s, %s, %s, %s)",
            (booking_id, airline_code, flight_number, flight_date, seat_class)
        )
        conn.commit()
        flash("Booking successfully completed!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Booking failed: {e}", "error") # This will catch your Trigger error if they have no card!
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('index'))

# --- 4.5 MANAGE BOOKINGS ---
@app.route('/manage', methods=['GET', 'POST'])
def manage():
    bookings = []
    email = None
    if request.method == 'POST':
        email = request.form['email']
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Fetch user's bookings
        query = """
            SELECT b.booking_id, b.total_price, bf.airline_code, bf.flight_number, bf.flight_date, bf.seat_class
            FROM booking b
            JOIN booking_flight bf ON b.booking_id = bf.booking_id
            WHERE b.email = %s;
        """
        cursor.execute(query, (email,))
        bookings = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
    return render_template('manage.html', bookings=bookings, email=email)

# --- 4.5 CANCEL BOOKING ---
@app.route('/cancel/<int:booking_id>', methods=['POST'])
def cancel(booking_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Must delete from junction table first due to Foreign Key constraints
        cursor.execute("DELETE FROM booking_flight WHERE booking_id = %s", (booking_id,))
        cursor.execute("DELETE FROM booking WHERE booking_id = %s", (booking_id,))
        conn.commit()
        flash("Booking successfully canceled.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error canceling booking: {e}", "error")
    finally:
        cursor.close()
        conn.close()
        
    return redirect(url_for('manage'))

if __name__ == '__main__':
    app.run(debug=True, port=5001)