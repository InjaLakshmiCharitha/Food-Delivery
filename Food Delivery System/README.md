# Food Delivery System — FastAPI

# Project Overview

The Food Delivery System is a backend application developed using FastAPI and MySQL. It allows customers to discover nearby restaurants, add food items to their cart, apply coupons, place orders, and track deliveries in real time.

Restaurant owners can manage restaurant orders, while delivery partners can accept deliveries, update their availability, share their locations, and verify deliveries using OTP authentication.

The system also includes JWT authentication, role-based access control, WebSockets, scheduled background jobs, and automated tests.

# Technologies Used

- **Language:** Python 3.9+
- **Framework:** FastAPI
- **Database:** MySQL
- **ORM:** SQLAlchemy
- **Database Migrations:** Alembic
- **Validation:** Pydantic
- **Authentication:** JWT
- **Password Hashing:** Passlib / bcrypt
- **Real-Time Communication:** WebSockets
- **Scheduled Tasks:** APScheduler
- **ASGI Server:** Uvicorn
- **Testing:** Pytest
- **API Testing:** Swagger UI

# Main Features

# Authentication and Authorization
- User registration and login.
- JWT-based authentication.
- Password hashing.
- Role-based access control.
- Support for customers, restaurant owners, delivery partners, and administrators.
- Approval workflow for roles that require administrative approval.

# Restaurant Management
- Restaurant registration and management.
- Restaurant menu management.
- Search for nearby restaurants using location information.
- Restaurant order management.
- Order preparation and status updates.

# Cart and Coupons
- Add food items to the cart.
- Update or remove cart items.
- Calculate cart totals.
- Apply eligible discount coupons.
- Calculate the discounted order amount.

# Order Management
- Place food orders.
- Generate order records and track order status.
- Calculate delivery charges based on distance.
- Apply surge pricing during configured peak hours.
- Support scheduled orders.
- Manage order status changes.

# Delivery Management
- Assign eligible delivery partners based on location and availability.
- Allow delivery partners to update their online status.
- Update delivery partner location.
- Track delivery progress.
- Verify delivery using an OTP.
- Limit repeated invalid OTP attempts.

# Real-Time Tracking
- WebSocket-based communication.
- Live order and delivery tracking updates.
- Real-time status notifications where supported by the application.

# Background Jobs
- Process eligible scheduled orders.
- Retry assignment of eligible unassigned orders.
- Run scheduled tasks using APScheduler.

# Ratings and Reports
- Submit ratings for completed orders or deliveries, as supported by the API.
- Generate administrative reports.
- Retrieve order and delivery information for reporting.

# Project Structure

The project uses the existing application structure.

Food Delivery System/
│
├── app/
│   ├── main.py
│   ├── database.py
│   │
│   ├── models/
│   │   └── models.py
│   │
│   ├── schemas/
│   │
│   ├── routers/
│   │   ├── auth.py
│   │   ├── addresses.py
│   │   ├── admin.py
│   │   ├── cart.py
│   │   ├── coupons.py
│   │   ├── delivery.py
│   │   ├── nearby.py
│   │   ├── orders.py
│   │   ├── ratings.py
│   │   ├── reports.py
│   │   ├── restaurants.py
│   │   ├── restaurant_orders.py
│   │   └── tracking.py
│   │
│   ├── utils/
│   ├── websockets/
│   └── jobs/
│       └── jobs.py
│
├── alembic/
│   └── versions/
├── tests/
│   └── test_orders.py
├──static/
├──venv/
├──.env
├── .env.example
├── alembic.ini
├── requirements.txt
└── README.md

*The tree above summarizes the main project components; some folders may contain additional files.*

# Prerequisites

Install the following before running the application:
- Python 3.9 or later.
- MySQL Server.
- Visual Studio Code or another Python editor.
- Git, if you want to manage the project using version control.

Docker is not required to run this project.

# Installation and Setup

# Open the project

Open the `Food Delivery System` folder in Visual Studio Code.

# Create and activate a virtual environment

On Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

# Install dependencies

```powershell
pip install -r requirements.txt
```

If Pytest is not already included in your requirements:

```powershell
pip install pytest
```

# Create the MySQL database

Open MySQL and execute:

```sql
CREATE DATABASE food_delivery_db;
```

If your application already uses a different database name, use that name instead.

# Configure environment variables

Create or update the `.env` file in the project root. Use the variable names expected by your existing `app/database.py` and authentication code.

Example configuration:

```env
DATABASE_URL=mysql+pymysql://YOUR_USERNAME:YOUR_PASSWORD@localhost:3306/food_delivery_db
SECRET_KEY=replace_with_a_secure_random_secret
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

Replace the example username, password, and secret with your own values. If your project uses `mysql+aiomysql` or different environment variable names, retain the configuration required by your current code.

**Security:** Never commit real database credentials, JWT secrets, or other private configuration to GitHub. Add `.env` to `.gitignore`.

# Apply database migrations

Run the following from the project root:

```powershell
alembic upgrade head
```

This applies the available Alembic migrations to the configured database.

# Start the application

```powershell
uvicorn app.main:app --reload
```

The server should start at:

```text
http://127.0.0.1:8000
```

# API Documentation

After starting the server, open Swagger UI:

**Swagger UI:** http://127.0.0.1:8000/docs

Alternative documentation:

**ReDoc:** http://127.0.0.1:8000/redoc

Use Swagger UI to register users, authenticate, authorize protected endpoints with a JWT token, and test the available APIs.

The exact endpoints and request schemas are available in the running Swagger documentation.

# Automated Testing

The project includes Pytest tests for delivery fee calculations.

Run the tests from the project root:
pytest -v

The current delivery fee test suite contains five tests covering:

- Delivery fees within the first 3 km.
- Delivery fees at exactly 3 km.
- Delivery fees above 3 km.
- Delivery fee calculation with surge pricing.
- Rejection of an invalid surge multiplier.

**Current test result:** All five delivery fee tests passed during development.

# Bonus Features

# Surge Pricing
Delivery charges can increase during configured peak periods. The current implementation uses a surge multiplier for configured lunch and dinner hours.

# Scheduled Orders
Customers can schedule eligible orders for a future date and time. Background jobs process scheduled orders when they become eligible.

# Suggested Testing Workflow

1. Register and log in with the required user roles.
2. Test role-specific access restrictions.
3. Create or manage a restaurant and its menu.
4. Add food items to the cart.
5. Apply a valid coupon and verify the calculated total.
6. Place an immediate order.
7. Test a scheduled order.
8. Verify restaurant order status updates.
9. Test delivery partner availability and assignment.
10. Test live tracking and delivery OTP verification.
11. Run the Pytest suite.
12. Check reports and ratings endpoints.

Test each endpoint against its actual request schema and authorization requirements in Swagger UI.

## Important Notes

- MySQL must be running before starting the application.
- The '.env' file must match the configuration expected by the application.
- Database migrations should be applied before testing new database fields.
- Protected endpoints require valid authentication and the appropriate role.
- WebSocket endpoints must be tested using their documented connection URLs and authentication method.
- Email notifications or other external integrations require their corresponding configuration if enabled.

# Conclusion

The Food Delivery System demonstrates backend development using FastAPI, SQLAlchemy, MySQL, JWT authentication, role-based access control, location-aware delivery assignment, coupons, scheduled orders, WebSockets, and automated testing.

The project can be executed locally without Docker and tested through Swagger UI and Pytest.
