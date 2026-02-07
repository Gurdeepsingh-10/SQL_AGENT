-- Example database schema for testing the SQL Agent
-- This creates a sample e-commerce database

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(100) UNIQUE NOT NULL,
    full_name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT 1
);

-- Products table
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL,
    category VARCHAR(100),
    stock_quantity INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    total_amount DECIMAL(10, 2) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Order items table
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Insert sample data

-- Sample users
INSERT INTO users (email, username, full_name) VALUES
('john@example.com', 'john_doe', 'John Doe'),
('jane@example.com', 'jane_smith', 'Jane Smith'),
('bob@example.com', 'bob_wilson', 'Bob Wilson');

-- Sample products
INSERT INTO products (name, description, price, category, stock_quantity) VALUES
('Laptop Pro 15', 'High-performance laptop with 16GB RAM', 1299.99, 'Electronics', 50),
('Wireless Mouse', 'Ergonomic wireless mouse', 29.99, 'Electronics', 200),
('Office Desk', 'Adjustable standing desk', 399.99, 'Furniture', 30),
('Office Chair', 'Ergonomic office chair with lumbar support', 249.99, 'Furniture', 45),
('USB-C Cable', '6ft USB-C charging cable', 12.99, 'Electronics', 500),
('Monitor 27"', '4K UHD monitor', 449.99, 'Electronics', 75),
('Desk Lamp', 'LED desk lamp with adjustable brightness', 39.99, 'Furniture', 100),
('Keyboard', 'Mechanical keyboard with RGB lighting', 89.99, 'Electronics', 120);

-- Sample orders
INSERT INTO orders (user_id, total_amount, status) VALUES
(1, 1329.98, 'completed'),
(2, 649.98, 'completed'),
(1, 89.99, 'pending'),
(3, 1749.97, 'shipped');

-- Sample order items
INSERT INTO order_items (order_id, product_id, quantity, price) VALUES
(1, 1, 1, 1299.99),
(1, 2, 1, 29.99),
(2, 4, 1, 249.99),
(2, 3, 1, 399.99),
(3, 8, 1, 89.99),
(4, 1, 1, 1299.99),
(4, 6, 1, 449.99);
