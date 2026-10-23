# Sales Analysis MCP Server

A Model Context Protocol (MCP) server that provides comprehensive customer sales database access for Zava Retail DIY Business. This server enables AI assistants to query and analyze retail sales data through a secure, schema-aware interface.

## Features

- **Multi-table Schema Access**: Retrieve schemas for multiple database tables in a single request
- **Secure Query Execution**: Execute PostgreSQL queries with Row Level Security (RLS) support
- **Real-time Data**: Access current sales, inventory, and customer data
- **Date/Time Utilities**: Get current UTC timestamps for time-sensitive analysis
- **Flexible Deployment**: Supports both stdio and HTTP server modes

## Supported Tables

The server provides access to the following retail database tables:

- `retail.customers` - Customer information and profiles
- `retail.stores` - Store locations and details
- `retail.categories` - Product categories and hierarchies
- `retail.product_types` - Product type classifications
- `retail.products` - Product catalog and specifications
- `retail.orders` - Customer orders and transactions
- `retail.order_items` - Individual items within orders
- `retail.inventory` - Current inventory levels and stock data

## Tools Available

### `get_multiple_table_schemas`

Retrieve database schemas for multiple tables in a single request.

**Parameters:**

- `table_names` (list[str]): List of valid table names from the supported tables above

**Returns:** Concatenated schema strings for the requested tables

### `execute_sales_query`

Execute PostgreSQL queries against the sales database with Row Level Security.

**Parameters:**

- `postgresql_query` (str): A well-formed PostgreSQL query

**Returns:** Query results formatted as a string (limited to 20 rows for readability)

**Best Practices:**

- Always fetch table schemas first
- Use exact column names from schemas
- Join related tables for comprehensive analysis
- Aggregate results when appropriate
- Limit output for readability

### `get_current_utc_date`

Get the current UTC date and time in ISO format.

**Returns:** Current UTC date/time in ISO format (YYYY-MM-DDTHH:MM:SS.fffffZ)

### `rank_capital_tied_up`

Rank products by the cost value of stock held beyond a target number of months of cover.

**Parameters:**

- `store_id` (int, optional): Rank a single store. Leave empty for every store the current user can see
- `window_days` (int, default 365): Sales history, ending today, used to measure demand. Future-dated orders are excluded
- `target_months_cover` (int, default 6): Months of sales a product should hold. Stock above this counts as excess
- `top_n` (int, default 20, max 50): Number of products to return

**Returns:** JSON with, per product, stock units and value, units sold in the window, months of cover, excess units and value, share of total excess, the total excess in scope, and the total stock units and value in scope (`total_stock_units_in_scope`, `total_stock_value_in_scope`). Each product also has `peak_month`, `months_until_peak`, `peak_is_near` and a `clearance_guard` that says whether clearing is blocked by the category's seasonal peak. A `scope` field names the stores covered. An empty result includes a message.

### `compare_store_coverage`

Compare each store's stock with its share of demand, per category.

**Parameters:**

- `category_name` (str, optional): For example `HARDWARE`. Leave empty for every category
- `window_days` (int, default 365): Sales history, ending today, used to measure demand

**Returns:** JSON with, per store and category, stock units and value, units sold, months of cover, share of stock, share of sales, and `units_over_equal_cover` (stock above what equal cover across stores would give; negative is below). The result is a relative imbalance, not a shortage. A `scope` field names the stores covered, and a note appears when only one store is visible.

### `seasonal_baseline_check`

Give a category's seasonal pattern and how recent months compare with it.

**Parameters:**

- `category_name` (str): For example `GARDEN & OUTDOOR`. An unknown name returns the valid list
- `store_id` (int, optional): Leave empty for every store the current user can see
- `recent_months` (int, default 6): Number of recent complete months to compare

**Returns:** JSON with the seasonal index by month (1.0 is an average month), the peak month, months until the peak, `peak_is_near` (true when the peak is within 3 months), and recent actual versus expected units. The current month and future-dated orders are excluded. Nothing is reported with fewer than 2 complete calendar years. Lead times are not in the data.

### `store_seasonal_alignment`

Ranks stores from most to least aligned with the yearly sales pattern of all visible stores together (correlation of the 12 monthly indexes, average monthly gap, peak and quietest month). Optional `category_name`. A user who can see one store gets a message instead.

### `stock_cover_ranking`

Ranks products (`by="product"`) or store and product pairs (`by="store_product"`) by months of stock cover. `min_months_cover=60` means more than 5 years of stock. The summary gives the count over the threshold and its share.

### `frequently_bought_together`

Ranks pairs of products in the same order, with orders together, how many times more often than chance, and order counts by season. Optional `store_id`, `category_name`, `season`, `year`, `min_orders`, `top_n`. Pairs under 20 orders are flagged as too thin to trust.

### `recent_order_lines`

Lists the newest order lines, newest first, one row per order line. The order is fixed (order date, then order id, then line id), so the same question gives the same lines. The summary gives `latest_order_date` and `order_lines_on_that_date`, because many lines share the newest date. Optional `store_name`, `category_name`, `skus`, `top_n` (at most 50). Orders dated after today are excluded.

### `find_products`

Finds products by SKU (`sku_starts_with`, `sku_ends_with`, `sku_contains`), by `name_contains` (every word must appear; a plural "s" is ignored) or by `category_name`, and gives each product's stock, summed by the database over every match. Optional `store_name`, `by_store` (stock per store), `include_details` (cost and description) and `top_n` (default 50, at most 100). The summary gives `products_matching` and `products_returned`, so a long list is never silently cut short. A typed `%` or `_` matches itself.

### `year_over_year_summary`

Compare one calendar year with another.

**Parameters:**

- `year` (int): Calendar year to examine, for example `2023`
- `compare_year` (int, optional): Year to compare with. Defaults to the year before `year`

**Returns:** JSON with units, revenue, orders and customers for both years, with absolute and percentage change, in total and by store, by category and by calendar month, plus `biggest_movers` (by amount and by percentage). Months are paired by calendar month. If either year is the current one, both years cover the same dates. Orders dated after today are excluded. A year with no orders returns a message with the first and last order dates. The data holds no reasons for a change.

Every tool result that has a `scope` field also reports `covers_all_stores`, which is true only when the current user can see every store.

## Security Features

### Row Level Security (RLS)

The server implements Row Level Security to ensure users only access data they're authorized to view:

- **HTTP Mode**: Uses `x-rls-user-id` header to identify the requesting user
- **Stdio Mode**: Uses `--RLS_USER_ID` command line argument
- **Default Fallback**: Uses placeholder UUID when no user ID is provided

#### Store-Specific RLS User IDs

Each Zava Retail store location has a unique RLS user ID that determines which data the user can access:

| Store Location | RLS User ID | Description |
|---------------|-------------|-------------|
| **Global Access** | `00000000-0000-0000-0000-000000000000` | Default fallback - all store access |
| **Seattle** | `f47ac10b-58cc-4372-a567-0e02b2c3d479` | Zava Retail Seattle store data |
| **Bellevue** | `6ba7b810-9dad-11d1-80b4-00c04fd430c8` | Zava Retail Bellevue store data |
| **Tacoma** | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` | Zava Retail Tacoma store data |
| **Spokane** | `d8e9f0a1-b2c3-4567-8901-234567890abc` | Zava Retail Spokane store data |
| **Everett** | `3b9ac9fa-cd5e-4b92-a7f2-b8c1d0e9f2a3` | Zava Retail Everett store data |
| **Redmond** | `e7f8a9b0-c1d2-3e4f-5678-90abcdef1234` | Zava Retail Redmond store data |
| **Kirkland** | `9c8b7a65-4321-fed0-9876-543210fedcba` | Zava Retail Kirkland store data |
| **Online** | `2f4e6d8c-1a3b-5c7e-9f0a-b2d4f6e8c0a2` | Zava Retail Online store data |

#### RLS Implementation

When a user connects with a specific store's RLS User ID, they will only see:

- Customers associated with that store
- Orders placed at that store location
- Inventory data for that specific store
- Store-specific sales and performance metrics

This ensures data isolation between different store locations while maintaining a unified database schema.

## Installation & Setup

### Prerequisites

- Docker
- VS Code with DevContainer extension
  
### Opening the Project

1. Open the project in VS Code.
2. If prompted, reopen in a DevContainer to ensure all dependencies are available.

### Dependencies

```python
# Core dependencies from the code
from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field
from sales_analysis_postgres import PostgreSQLSchemaProvider
```

### Environment Configuration

The project includes predefined RLS User IDs for each store location in the `.env` file:

```properties
# Default Group Access ID
RLS_USER_ID="00000000-0000-0000-0000-000000000000" 

# Store-specific RLS User IDs
# Zava Retail Seattle
# RLS_USER_ID="f47ac10b-58cc-4372-a567-0e02b2c3d479"

# Zava Retail Bellevue  
# RLS_USER_ID="6ba7b810-9dad-11d1-80b4-00c04fd430c8"

# Zava Retail Online
# RLS_USER_ID="2f4e6d8c-1a3b-5c7e-9f0a-b2d4f6e8c0a2"
# ... (additional store configurations)
```

You can uncomment and use the appropriate RLS_USER_ID for your target store location.

## Usage

The following assumes you'll be using the built-in VS Code MCP server support.

### Running in Stdio Mode

Start the **zava-sales-analysis-stdio** server using the `.vscode/mcp.json` configuration:

```json
{
    "servers": {
        "zava-sales-analysis-stdio": {
            "type": "stdio",
            "command": "python",
            "args": [
                "${workspaceFolder}/src/python/mcp_server/sales_analysis/sales_analysis.py",
                "--stdio",
                "--RLS_USER_ID=00000000-0000-0000-0000-000000000000"
            ]
        },
        "zava-customer-sales-stdio": {
            "type": "stdio",
            "command": "python",
            "args": [
                "${workspaceFolder}/src/python/mcp_server/customer_sales/customer_sales.py",
                "--stdio",
                "--RLS_USER_ID=00000000-0000-0000-0000-000000000000"
            ]
        },
        "zava-diy-http": {
            "url": "http://127.0.0.1:8000/mcp",
            "type": "http"
        }
    },
    "inputs": []
}
```

### Start the Customer Sales MCP Server in Streamable HTTP Mode

1. Start the MCP server in stdio mode:

    From VS Code, open the customer_sales.py file and run it directly by clicking the "Run" button in VS Code.

    or from the command line, run:

    ```bash
    cd src/python/mcp_server/sales_analysis
    python sales_analysis.py
    ```

2. Enable the MCP server from the mcp.json configuration

    Start the **zava-diy-http** server using the `.vscode/mcp.json` configuration:

    ```json
    {
        "servers": {
            "zava-sales-analysis-stdio": {
                "type": "stdio",
                "command": "python",
                "args": [
                    "${workspaceFolder}/src/python/mcp_server/sales_analysis/sales_analysis.py",
                    "--stdio",
                    "--RLS_USER_ID=00000000-0000-0000-0000-000000000000"
                ]
            },
            "zava-customer-sales-stdio": {
                "type": "stdio",
                "command": "python",
                "args": [
                    "${workspaceFolder}/src/python/mcp_server/customer_sales/customer_sales.py",
                    "--stdio",
                    "--RLS_USER_ID=00000000-0000-0000-0000-000000000000"
                ]
            },
            "zava-diy-http": {
                "url": "http://127.0.0.1:8000/mcp",
                "type": "http"
            }
        },
        "inputs": []
    }
    ```

## Sample Queries

1. Show top 20 products by sales revenue
1. Show sales by store
1. What were the last quarter's sales by category?

## Architecture

### Application Context

The server uses a managed application context with:

- **Database Connection Pool**: Efficient connection management for HTTP mode
- **Lifecycle Management**: Proper resource cleanup on shutdown
- **Type Safety**: Strongly typed context with `AppContext` dataclass

### Request Context

- **Header Extraction**: Secure header parsing for user identification
- **RLS Integration**: Automatic user ID resolution from request context
- **Error Handling**: Comprehensive error handling with user-friendly messages

## Database Integration

The server integrates with a PostgreSQL database through the `PostgreSQLSchemaProvider` class:

- **Connection Pooling**: Uses async connection pools for scalability
- **Schema Metadata**: Provides detailed table schema information
- **Query Execution**: Secure query execution with RLS support
- **Resource Management**: Automatic cleanup of database resources

## Error Handling

The server implements robust error handling:

- **Table Validation**: Ensures only valid table names are accessed
- **Query Validation**: Validates PostgreSQL queries before execution
- **Resource Management**: Proper cleanup even during errors
- **User-Friendly Messages**: Clear error messages for troubleshooting

## Example Usage

### Getting Table Schemas

```python
# Get schemas for customers and orders tables
schemas = await get_multiple_table_schemas(
    table_names=["retail.customers", "retail.orders"]
)
```

### Executing Queries

```python
# Analyze sales by category
query = """
SELECT 
    c.category_name,
    COUNT(oi.order_item_id) as total_items_sold,
    SUM(oi.quantity * oi.unit_price) as total_revenue
FROM retail.categories c
JOIN retail.products p ON c.category_id = p.category_id
JOIN retail.order_items oi ON p.product_id = oi.product_id
GROUP BY c.category_name
ORDER BY total_revenue DESC
LIMIT 20;
"""
results = await execute_sales_query(query)
```

## Security Considerations

1. **Row Level Security**: All queries respect RLS policies based on user identity
2. **Store Data Isolation**: Each store's RLS User ID ensures access only to that store's data
3. **Input Validation**: Table names and queries are validated before execution
4. **Resource Limits**: Query results are limited to prevent excessive resource usage
5. **Connection Security**: Uses secure database connection practices
6. **User Identity Verification**: Always ensure the correct RLS User ID is used for the intended store location

### Important Security Notes

- **Never use production RLS User IDs in development environments**
- **Always verify the RLS User ID matches the intended store before running queries**
- **The default UUID (`00000000-0000-0000-0000-000000000000`) provides limited access**
- **Each store manager should only have access to their store's RLS User ID**

## Development

### Project Structure

```
sales_analysis/
├── sales_analysis.py          # Main MCP server implementation
├── sales_analysis_postgres.py # PostgreSQL integration layer
└── README.md                  # This documentation
```

### Key Components

- **FastMCP Server**: Modern MCP server implementation with async support
- **PostgreSQL Provider**: Database abstraction layer with RLS support
- **Context Management**: Type-safe application and request context handling
- **Tool Registration**: Declarative tool registration with Pydantic validation

## Contributing

When contributing to this server:

1. Ensure all database queries respect Row Level Security
2. Add proper error handling for new tools
3. Update this README with any new features or changes
4. Test both stdio and HTTP server modes
5. Validate input parameters and provide clear error messages

## License

[Include appropriate license information]

---

*This MCP server enables secure, efficient access to Zava Retail sales data for AI-powered analysis and insights.*
