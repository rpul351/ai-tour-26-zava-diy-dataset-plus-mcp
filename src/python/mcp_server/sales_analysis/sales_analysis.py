#!/usr/bin/env python3
"""
Provides comprehensive customer sales database access with individual table schema tools for Zava Retail DIY Business.
"""

import argparse
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Optional

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field
from sales_analysis_postgres import PostgreSQLSchemaProvider

import sys
from functools import partial

print = partial(print, file=sys.stderr)  # stdout carries the MCP protocol in stdio mode

RLS_USER_ID = None


@dataclass
class AppContext:
    """Application context containing database connection."""

    db: PostgreSQLSchemaProvider


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle with type-safe context"""

    db = PostgreSQLSchemaProvider()
    # Use connection pool instead of single connection for HTTP server
    await db.create_pool()

    try:
        yield AppContext(db=db)
    finally:
        # Cleanup on shutdown
        try:
            await db.close_pool()
        except Exception as e:
            print(f"⚠️  Error closing database pool: {e}")


# Create MCP server with lifespan support
mcp = FastMCP("mcp-zava-sales", lifespan=app_lifespan, stateless_http=True)


def get_header(ctx: Context, header_name: str) -> Optional[str]:
    """Extract a specific header from the request context."""

    request = ctx.request_context.request
    if request is not None and hasattr(request, "headers"):
        headers = request.headers
        if headers:
            header_value = headers.get(header_name)
            if header_value is not None:
                if isinstance(header_value, bytes):
                    return header_value.decode("utf-8")
                return str(header_value)

    return None


def get_rls_user_id(ctx: Context) -> str:
    """Get the Row Level Security User ID from the request context."""

    # if running in stdio mode, use the global RLS_USER_ID passed as an argument
    if RLS_USER_ID is not None:
        return RLS_USER_ID

    rls_user_id = get_header(ctx, "x-rls-user-id")
    if rls_user_id is None:
        # Default to a placeholder if not provided
        rls_user_id = "00000000-0000-0000-0000-000000000000"
    return rls_user_id


def get_db_provider() -> PostgreSQLSchemaProvider:
    """Get the database provider instance from context."""
    ctx = mcp.get_context()
    app_context = ctx.request_context.lifespan_context
    if isinstance(app_context, AppContext):
        return app_context.db
    raise RuntimeError("Invalid lifespan context type")


@mcp.tool()
async def get_multiple_table_schemas(
    ctx: Context,
    table_names: Annotated[
        list[str],
        Field(
            description="List of table names. Valid table names include 'retail.customers', 'retail.stores', 'retail.categories', 'retail.product_types', 'retail.products', 'retail.orders', 'retail.order_items', 'retail.inventory'."
        ),
    ],
) -> str:
    """
    Retrieve schemas for multiple tables. Use this tool only for schemas you have not already fetched during the conversation.

    Args:
        table_names: List of table names. Valid table names include 'retail.customers', 'retail.stores', 'retail.categories', 'retail.product_types', 'retail.products', 'retail.orders', 'retail.order_items', 'retail.inventory'.

    Returns:
        Concatenated schema strings for the requested tables.
    """

    rls_user_id = get_rls_user_id(ctx)

    if not table_names:
        return "Error: table_names parameter is required and cannot be empty"

    valid_tables = {
        "retail.customers",
        "retail.stores",
        "retail.categories",
        "retail.product_types",
        "retail.products",
        "retail.orders",
        "retail.order_items",
        "retail.inventory",
    }

    # Validate table names
    invalid_tables = [name for name in table_names if name not in valid_tables]
    if invalid_tables:
        return f"Error: Invalid table names: {invalid_tables}. Valid tables are: {sorted(valid_tables)}"

    print(f"Manager ID: {rls_user_id}")
    print(f"Retrieving schemas for tables: {', '.join(table_names)}")

    try:
        provider = get_db_provider()
        return await provider.get_table_metadata_from_list(table_names, rls_user_id=rls_user_id)
    except Exception as e:
        return f"Error retrieving table schemas: {e!s}"


@mcp.tool()
async def execute_sales_query(
    ctx: Context, postgresql_query: Annotated[str, Field(description="A well-formed PostgreSQL query.")]
) -> str:
    """Always fetch table schemas first, use exact column names, join related tables for clarity, aggregate results, limit output to 20 rows, and explain that results are limited for readability.

    Args:
        postgresql_query: A well-formed PostgreSQL query.

    Returns:
        Query results as a string.
    """

    rls_user_id = get_rls_user_id(ctx)

    print(f"Manager ID: {rls_user_id}")
    print(f"Executing PostgreSQL query: {postgresql_query}")

    try:
        if not postgresql_query:
            return "Error: postgresql_query parameter is required"

        provider = get_db_provider()
        result = await provider.execute_query(postgresql_query, rls_user_id=rls_user_id)
        return f"Query Results:\n{result}"

    except Exception as e:
        return f"Error executing database query: {e!s}"


@mcp.tool()
async def get_current_utc_date() -> str:
    """Get the current UTC date and time in ISO format. Useful for date-based queries, filtering recent data, or understanding the current context for time-sensitive analysis.

    Returns:
        Current UTC date and time in ISO format (YYYY-MM-DDTHH:MM:SS.fffffZ)
    """
    print("Retrieving current UTC date and time")
    try:
        current_utc = datetime.now(timezone.utc)
        return f"Current UTC Date/Time: {current_utc.isoformat()}"
    except Exception as e:
        return f"Error retrieving current UTC date: {e!s}"


@mcp.tool()
async def get_inventory_optimization_overview(
    ctx: Context,
    store_id: Annotated[
        Optional[int],
        Field(description="Optional store ID to focus the analysis on a single store. Leave empty to review the full network."),
    ] = None,
    days_window: Annotated[
        int,
        Field(description="Recent sales window in days used to estimate demand. Typical values are 7, 14, 30, or 90.", ge=7, le=365),
    ] = 30,
) -> str:
    """Return product-level inventory health across stores using recent demand, days-of-cover, and risk status.

    This tool is designed for inventory optimization workflows such as identifying overstock,
    understock, and products at risk of stockout. It honors the current RLS user context.
    """
    rls_user_id = get_rls_user_id(ctx)
    provider = get_db_provider()
    return await provider.get_inventory_optimization_overview(
        rls_user_id=rls_user_id,
        store_id=store_id,
        days_window=days_window,
    )


@mcp.tool()
async def recommend_inventory_transfers(
    ctx: Context,
    store_id: Annotated[
        Optional[int],
        Field(description="Optional store ID to focus on a single store. Leave empty to find opportunities across the network."),
    ] = None,
    days_window: Annotated[
        int,
        Field(description="Recent sales history window in days used to measure demand.", ge=7, le=365),
    ] = 30,
    critical_days: Annotated[
        int,
        Field(description="Threshold for a critical shortage in days of cover.", ge=1, le=30),
    ] = 7,
    surplus_days: Annotated[
        int,
        Field(description="Minimum days of cover required before a store can act as a surplus source.", ge=7, le=90),
    ] = 21,
) -> str:
    """Recommend transfers from stores with excess stock to stores with shortage risk.

    Returns product-level opportunities, priority, and suggested transfer quantities.
    """
    rls_user_id = get_rls_user_id(ctx)
    provider = get_db_provider()
    return await provider.recommend_inventory_transfers(
        rls_user_id=rls_user_id,
        store_id=store_id,
        days_window=days_window,
        critical_days=critical_days,
        surplus_days=surplus_days,
    )


@mcp.tool()
async def rank_capital_tied_up(
    ctx: Context,
    store_id: Annotated[
        Optional[int],
        Field(description="Optional store ID to rank a single store. Leave empty for every store the current user can see."),
    ] = None,
    window_days: Annotated[
        int,
        Field(description="Sales history in days, ending today, used to measure demand. Future-dated orders are excluded.", ge=30, le=1095),
    ] = 365,
    target_months_cover: Annotated[
        int,
        Field(description="Months of sales a product should hold. Stock above this counts as excess.", ge=1, le=36),
    ] = 6,
    top_n: Annotated[
        int,
        Field(description="Number of products to return, ranked by excess value.", ge=1, le=50),
    ] = 20,
) -> str:
    """Rank products by the cost value of stock held beyond a target months of cover, to find where capital is tied up.

    Returns, per product: stock units and value, units sold in the window, months of cover,
    excess units and value, and each product's share of the total excess in scope.
    Use this before recommending that purchasing is held. It does not say whether the excess is
    seasonal, so check the product's seasonal pattern before recommending that stock is cleared.
    It honors the current RLS user context.
    """
    rls_user_id = get_rls_user_id(ctx)
    provider = get_db_provider()
    return await provider.rank_capital_tied_up(
        rls_user_id=rls_user_id,
        store_id=store_id,
        window_days=window_days,
        target_months_cover=target_months_cover,
        top_n=top_n,
    )


@mcp.tool()
async def compare_store_coverage(
    ctx: Context,
    category_name: Annotated[
        Optional[str],
        Field(description="Optional category name, for example 'HARDWARE'. Leave empty for every category."),
    ] = None,
    window_days: Annotated[
        int,
        Field(description="Sales history in days, ending today, used to measure demand. Future-dated orders are excluded.", ge=30, le=1095),
    ] = 365,
) -> str:
    """Compare each store's stock with its share of demand, per category, to see whether stock follows demand.

    Returns, per store and category: stock units and value, units sold, months of cover, share of stock,
    share of sales, and the units held above what equal cover across stores would give.
    The result includes a scope field naming the stores covered. Only call a result a network total
    if every store is listed. A positive imbalance is a relative surplus, not a shortage.
    It honors the current RLS user context.
    """
    rls_user_id = get_rls_user_id(ctx)
    provider = get_db_provider()
    return await provider.compare_store_coverage(
        rls_user_id=rls_user_id,
        category_name=category_name,
        window_days=window_days,
    )


@mcp.tool()
async def seasonal_baseline_check(
    ctx: Context,
    category_name: Annotated[
        str,
        Field(description="Category name, for example 'GARDEN & OUTDOOR'. An unknown name returns the valid list."),
    ],
    store_id: Annotated[
        Optional[int],
        Field(description="Optional store ID. Leave empty for every store the current user can see."),
    ] = None,
    recent_months: Annotated[
        int,
        Field(description="Number of most recent complete months to compare with the seasonal pattern.", ge=1, le=24),
    ] = 6,
) -> str:
    """Give a category's seasonal pattern, its peak month, how many months until the peak, and how recent months compare.

    Use this before recommending that stock is cleared or bought. Months of the current period and
    future-dated orders are excluded. It reports nothing if the scope has fewer than 2 complete calendar years.
    Lead times are not in the data. It honors the current RLS user context.
    """
    rls_user_id = get_rls_user_id(ctx)
    provider = get_db_provider()
    return await provider.seasonal_baseline_check(
        rls_user_id=rls_user_id,
        category_name=category_name,
        store_id=store_id,
        recent_months=recent_months,
    )


@mcp.tool()
async def year_over_year_summary(
    ctx: Context,
    year: Annotated[
        int,
        Field(description="Calendar year to examine, for example 2023.", ge=1900, le=2100),
    ],
    compare_year: Annotated[
        Optional[int],
        Field(description="Year to compare with. Defaults to the year before `year`.", ge=1900, le=2100),
    ] = None,
) -> str:
    """Compare one calendar year with another: totals, by store, by category and by calendar month.

    Use this for questions such as "what happened in 2023" or "how did 2024 compare with 2023".
    Returns units, revenue, orders and customers for both years, with absolute and percentage change.
    Months are paired by calendar month. If either year is the current one, both years cover the same
    part of the year. Orders dated after today are excluded. The data holds no reasons for a change.
    The result includes a scope field naming the stores covered. It honors the current RLS user context.
    """
    rls_user_id = get_rls_user_id(ctx)
    provider = get_db_provider()
    return await provider.year_over_year_summary(
        rls_user_id=rls_user_id,
        year=year,
        compare_year=compare_year,
    )


async def run_http_server() -> None:
    """Run the MCP server in HTTP mode."""
    print(f"📡 MCP endpoint available at: http://{mcp.settings.host}:{mcp.settings.port}/mcp")

    # Run the FastMCP server as HTTP endpoint
    await mcp.run_streamable_http_async()


def main() -> None:
    """Main entry point for the MCP server."""
    global RLS_USER_ID

    parser = argparse.ArgumentParser()
    parser.add_argument("--stdio", action="store_true", help="Run server in stdio mode")
    parser.add_argument("--RLS_USER_ID", type=str, default=None, help="Row Level Security User ID")
    args = parser.parse_args()

    # if running in stdio mode, set the global RLS_USER_ID
    RLS_USER_ID = args.RLS_USER_ID

    if args.stdio:
        mcp.run()
    else:
        # Run the HTTP server
        asyncio.run(run_http_server())


if __name__ == "__main__":
    main()
