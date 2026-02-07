# Natural Language to SQL - Example Queries

This document demonstrates example natural language queries and their expected SQL translations.

## Basic Queries

### Example 1: Simple SELECT
**Natural Language**: "Show me all users"

**Expected SQL**:
```sql
SELECT * FROM users;
```

**Intent**: QUERY

---

### Example 2: Filtered SELECT
**Natural Language**: "Show me all products in the Electronics category"

**Expected SQL**:
```sql
SELECT * FROM products WHERE category = 'Electronics';
```

**Intent**: QUERY

---

### Example 3: COUNT Aggregation
**Natural Language**: "How many users do we have?"

**Expected SQL**:
```sql
SELECT COUNT(*) as user_count FROM users;
```

**Intent**: QUERY

---

## Intermediate Queries

### Example 4: JOIN Query
**Natural Language**: "Show me all orders with user information"

**Expected SQL**:
```sql
SELECT orders.*, users.email, users.username 
FROM orders 
JOIN users ON orders.user_id = users.id;
```

**Intent**: QUERY

---

### Example 5: Date Filtering
**Natural Language**: "Show me users created in the last 7 days"

**Expected SQL**:
```sql
SELECT * FROM users 
WHERE created_at >= DATE('now', '-7 days');
```

**Intent**: QUERY

---

### Example 6: Price Range
**Natural Language**: "Find products between $50 and $500"

**Expected SQL**:
```sql
SELECT * FROM products 
WHERE price BETWEEN 50 AND 500;
```

**Intent**: QUERY

---

## Advanced Queries

### Example 7: Aggregation with GROUP BY
**Natural Language**: "What's the average price of products by category?"

**Expected SQL**:
```sql
SELECT category, AVG(price) as average_price 
FROM products 
GROUP BY category;
```

**Intent**: QUERY

---

### Example 8: Complex JOIN with Aggregation
**Natural Language**: "Show me total sales amount for each user"

**Expected SQL**:
```sql
SELECT users.username, SUM(orders.total_amount) as total_sales
FROM users
JOIN orders ON users.id = orders.user_id
GROUP BY users.id, users.username;
```

**Intent**: QUERY

---

### Example 9: Subquery
**Natural Language**: "Show me products that have never been ordered"

**Expected SQL**:
```sql
SELECT * FROM products 
WHERE id NOT IN (SELECT DISTINCT product_id FROM order_items);
```

**Intent**: QUERY

---

## Write Operations

### Example 10: INSERT
**Natural Language**: "Add a new product called 'Headphones' priced at $79.99 in Electronics category"

**Expected SQL**:
```sql
INSERT INTO products (name, price, category, stock_quantity) 
VALUES ('Headphones', 79.99, 'Electronics', 0);
```

**Intent**: INSERT

---

### Example 11: UPDATE
**Natural Language**: "Update the price of product with id 5 to $15.99"

**Expected SQL**:
```sql
UPDATE products 
SET price = 15.99 
WHERE id = 5;
```

**Intent**: UPDATE

---

### Example 12: UPDATE with Condition
**Natural Language**: "Mark all pending orders as shipped"

**Expected SQL**:
```sql
UPDATE orders 
SET status = 'shipped' 
WHERE status = 'pending';
```

**Intent**: UPDATE

---

## Schema Information Queries

### Example 13: Table List
**Natural Language**: "What tables are in the database?"

**Intent**: SCHEMA_INFO

**Response**: Returns list of all tables

---

### Example 14: Table Structure
**Natural Language**: "What columns does the products table have?"

**Intent**: SCHEMA_INFO

**Response**: Returns schema information for products table

---

## Edge Cases and Error Scenarios

### Example 15: Dangerous Operation (Should be Blocked)
**Natural Language**: "Delete all users"

**Expected Behavior**: Blocked by validator (DELETE operations disabled by default)

**Error Message**: "DELETE operations are not allowed"

---

### Example 16: DDL Operation (Should be Blocked)
**Natural Language**: "Drop the orders table"

**Expected Behavior**: Blocked by validator (DDL operations disabled)

**Error Message**: "Dangerous operations detected: DROP"

---

### Example 17: Ambiguous Query
**Natural Language**: "Show me the things"

**Expected Behavior**: Intent classification returns UNKNOWN

**Error Message**: "I couldn't understand your query. Please try rephrasing it."

---

## Response Format Examples

### Successful Query Response
```json
{
  "success": true,
  "intent": "QUERY",
  "generated_sql": "SELECT * FROM users;",
  "results": [
    {
      "id": 1,
      "email": "john@example.com",
      "username": "john_doe",
      "full_name": "John Doe"
    }
  ],
  "result_count": 1,
  "execution_time": 0.045,
  "message": "Query returned 1 row(s)"
}
```

### Failed Query Response
```json
{
  "success": false,
  "intent": "DELETE",
  "generated_sql": "DELETE FROM users;",
  "message": "The generated query failed security validation.",
  "error": "DELETE operations are not allowed"
}
```

---

## Tips for Users

1. **Be specific**: Include table names when possible
2. **Use clear conditions**: Specify exact filtering criteria
3. **Mention time frames**: Use "last 7 days", "this month", etc.
4. **Ask for counts**: Use "how many" for COUNT queries
5. **Request averages**: Use "average" or "mean" for AVG queries
6. **Specify sorting**: Use "sorted by" or "ordered by"
7. **Limit results**: Use "top 10" or "first 5" for LIMIT

## Common Patterns

- **Counting**: "How many [items] are there?"
- **Filtering**: "Show me [items] where [condition]"
- **Aggregating**: "What's the total/average/sum of [field]?"
- **Joining**: "Show me [table1] with [table2] information"
- **Time-based**: "Show me [items] from [time period]"
- **Sorting**: "Show me [items] sorted by [field]"
- **Top N**: "Show me the top 10 [items] by [field]"
