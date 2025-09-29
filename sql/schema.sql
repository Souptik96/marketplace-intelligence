-- DuckDB schema definition
CREATE TABLE daily_product_sales (
    product_title TEXT,
    category TEXT,
    day DATE,
    units INT,
    revenue DOUBLE
);
