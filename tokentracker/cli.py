"""CLI for viewing tracked LLM usage and costs."""

from __future__ import annotations

import json
import sys
from datetime import datetime

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from tokentracker import __version__

console = Console()


@click.group()
@click.version_option(__version__, prog_name="tokentracker")
def main():
    """TokenTracker — see where your LLM money goes."""
    pass


@main.command()
@click.option("--days", "-d", default=30, help="Number of days to look back")
def dashboard(days: int):
    """Show a summary dashboard of your LLM spending."""
    from tokentracker.query import cost_by_day, cost_by_endpoint, cost_by_model, summary

    s = summary(days=days)

    if s["total_calls"] == 0:
        console.print("[dim]No API calls tracked yet.[/dim]")
        console.print("\nGet started by replacing your OpenAI import:")
        console.print("[bold]from tokentracker import OpenAI[/bold]")
        return

    # Summary panel
    console.print()
    console.print(
        Panel(
            f"[bold]Total cost:[/bold] ${s['total_cost_usd']:.4f}\n"
            f"[bold]API calls:[/bold] {s['total_calls']:,}\n"
            f"[bold]Tokens:[/bold] {s['total_tokens']:,} "
            f"({s['total_input_tokens']:,} in / {s['total_output_tokens']:,} out)\n"
            f"[bold]Avg latency:[/bold] {s['avg_latency_ms']:.0f}ms\n"
            f"[bold]Models used:[/bold] {s['models_used']}",
            title=f"[bold cyan]TokenTracker — Last {days} days[/bold cyan]",
            border_style="cyan",
        )
    )

    # Cost by model
    models = cost_by_model(days=days)
    if models:
        console.print()
        t = Table(title="Cost by Model", show_lines=False)
        t.add_column("Model", style="bold")
        t.add_column("Calls", justify="right")
        t.add_column("Tokens", justify="right")
        t.add_column("Cost", justify="right", style="green")
        t.add_column("Avg Latency", justify="right", style="dim")
        for m in models:
            cost_str = f"${m['total_cost']:.4f}" if m["total_cost"] else "—"
            tokens = (m["input_tokens"] or 0) + (m["output_tokens"] or 0)
            t.add_row(
                m["model"],
                str(m["calls"]),
                f"{tokens:,}",
                cost_str,
                f"{m['avg_latency']:.0f}ms",
            )
        console.print(t)

    # Endpoint costs
    endpoints = cost_by_endpoint(days=days)
    if endpoints:
        console.print()
        t = Table(title="Cost by Endpoint", show_lines=False)
        t.add_column("Endpoint", style="bold")
        t.add_column("Calls", justify="right")
        t.add_column("Tokens", justify="right")
        t.add_column("Cost", justify="right", style="green")
        t.add_column("Avg Latency", justify="right", style="dim")
        for e in endpoints:
            cost_str = f"${e['total_cost']:.4f}" if e["total_cost"] else "—"
            tokens = (e["input_tokens"] or 0) + (e["output_tokens"] or 0)
            t.add_row(
                e["endpoint"],
                str(e["calls"]),
                f"{tokens:,}",
                cost_str,
                f"{e['avg_latency']:.0f}ms",
            )
        console.print(t)

    # Daily costs
    daily = cost_by_day(days=min(days, 14))
    if daily:
        console.print()
        t = Table(title="Daily Spending", show_lines=False)
        t.add_column("Date", style="bold")
        t.add_column("Calls", justify="right")
        t.add_column("Tokens", justify="right")
        t.add_column("Cost", justify="right", style="green")
        for d in daily:
            cost_str = f"${d['cost']:.4f}" if d["cost"] else "—"
            t.add_row(d["date"], str(d["calls"]), f"{d['tokens']:,}", cost_str)
        console.print(t)


@main.command()
@click.option("--limit", "-n", default=20, help="Number of recent calls to show")
def recent(limit: int):
    """Show recent API calls."""
    from tokentracker.query import recent as get_recent

    calls = get_recent(limit=limit)
    if not calls:
        console.print("[dim]No API calls tracked yet.[/dim]")
        return

    t = Table(title=f"Last {limit} API Calls", show_lines=False)
    t.add_column("Time", style="dim")
    t.add_column("Model", style="bold")
    t.add_column("Tokens", justify="right")
    t.add_column("Cost", justify="right", style="green")
    t.add_column("Latency", justify="right")
    t.add_column("Status")

    for c in calls:
        ts = datetime.fromtimestamp(c["timestamp"]).strftime("%m-%d %H:%M")
        cost_str = f"${c['cost_usd']:.4f}" if c["cost_usd"] else "—"
        status = "[green]ok[/green]" if c["status"] == "ok" else f"[red]{c['status']}[/red]"
        t.add_row(
            ts,
            c["model"],
            f"{c['total_tokens']:,}",
            cost_str,
            f"{c['latency_ms']:.0f}ms",
            status,
        )
    console.print(t)


@main.command()
@click.option("--days", "-d", default=30, help="Number of days to look back")
def endpoints(days: int):
    """Show usage and cost grouped by API endpoint."""
    from tokentracker.query import cost_by_endpoint

    rows = cost_by_endpoint(days=days)
    if not rows:
        console.print("[dim]No API calls tracked yet.[/dim]")
        return

    t = Table(title=f"Endpoint Usage — Last {days} days", show_lines=False)
    t.add_column("Endpoint", style="bold")
    t.add_column("Calls", justify="right")
    t.add_column("Input", justify="right")
    t.add_column("Output", justify="right")
    t.add_column("Cost", justify="right", style="green")
    t.add_column("Avg Latency", justify="right", style="dim")

    for row in rows:
        cost_str = f"${row['total_cost']:.4f}" if row["total_cost"] else "—"
        t.add_row(
            row["endpoint"],
            str(row["calls"]),
            f"{row['input_tokens'] or 0:,}",
            f"{row['output_tokens'] or 0:,}",
            cost_str,
            f"{row['avg_latency']:.0f}ms",
        )

    console.print(t)


@main.command()
@click.option("--limit", "limit_usd", type=float, required=True, help="Budget limit in USD")
@click.option("--days", "-d", default=30, help="Number of days to look back")
@click.option(
    "--warn-at",
    default=0.8,
    show_default=True,
    help="Print a warning when usage reaches this fraction of the limit",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON")
@click.option("--model", help="Only count calls using this exact model name")
@click.option("--endpoint", help="Only count calls using this API endpoint")
def budget(
    limit_usd: float,
    days: int,
    warn_at: float,
    json_output: bool,
    model: str | None,
    endpoint: str | None,
):
    """Check spending against a budget and exit non-zero when it is exceeded."""
    from tokentracker.query import summary

    if limit_usd <= 0:
        raise click.UsageError("--limit must be greater than zero")
    if days <= 0:
        raise click.UsageError("--days must be greater than zero")
    if warn_at <= 0:
        raise click.UsageError("--warn-at must be greater than zero")

    s = summary(days=days, model=model, endpoint=endpoint)
    spent = float(s["total_cost_usd"])
    ratio = spent / limit_usd
    remaining = max(limit_usd - spent, 0.0)
    status = "exceeded" if spent > limit_usd else "warn" if ratio >= warn_at else "ok"
    payload = {
        "status": status,
        "days": days,
        "limit_usd": round(limit_usd, 4),
        "spent_usd": round(spent, 4),
        "remaining_usd": round(remaining, 4),
        "usage_pct": round(ratio * 100, 1),
        "total_calls": s["total_calls"],
        "total_tokens": s["total_tokens"],
        "scope": {"model": model, "endpoint": endpoint},
    }

    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        style = "red" if status == "exceeded" else "yellow" if status == "warn" else "green"
        scope = " · ".join(part for part in [model, endpoint] if part) or "all calls"
        console.print(
            Panel(
                f"[bold]Spent:[/bold] ${spent:.4f} / ${limit_usd:.4f}\n"
                f"[bold]Usage:[/bold] {ratio * 100:.1f}%\n"
                f"[bold]Remaining:[/bold] ${remaining:.4f}\n"
                f"[bold]Calls:[/bold] {s['total_calls']:,}\n"
                f"[bold]Tokens:[/bold] {s['total_tokens']:,}",
                title=f"[bold {style}]Budget {status} · {scope} · last {days} days[/bold {style}]",
                border_style=style,
            )
        )

    if status == "exceeded":
        sys.exit(2)


@main.command()
@click.option("--days", "-d", default=7, show_default=True, help="Observed days to use")
@click.option("--forecast-days", default=30, show_default=True, help="Days to project")
@click.option("--model", help="Only count calls using this exact model name")
@click.option("--endpoint", help="Only count calls using this API endpoint")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON")
def forecast(
    days: int,
    forecast_days: int,
    model: str | None,
    endpoint: str | None,
    json_output: bool,
):
    """Project future spend from the current daily run rate."""
    from tokentracker.query import spend_forecast

    if days <= 0:
        raise click.UsageError("--days must be greater than zero")
    if forecast_days <= 0:
        raise click.UsageError("--forecast-days must be greater than zero")

    payload = spend_forecast(
        days=days,
        forecast_days=forecast_days,
        model=model,
        endpoint=endpoint,
    )
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return

    scope = " · ".join(part for part in [model, endpoint] if part) or "all calls"
    console.print(
        Panel(
            f"[bold]Observed spend:[/bold] ${payload['observed_cost_usd']:.4f}\n"
            f"[bold]Daily run rate:[/bold] ${payload['daily_cost_usd']:.4f}\n"
            f"[bold]Projected spend:[/bold] ${payload['projected_cost_usd']:.4f}\n"
            f"[bold]Projected calls:[/bold] {payload['projected_calls']:,}",
            title=(
                f"[bold cyan]Forecast · {scope} · "
                f"{days} observed days → {forecast_days} projected days[/bold cyan]"
            ),
            border_style="cyan",
        )
    )


@main.command()
@click.option("--days", "-d", default=30, show_default=True, help="Number of days to analyze")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON")
def insights(days: int, json_output: bool):
    """Surface spend anomalies, cost concentration and savings opportunities."""
    from tokentracker.query import insights as get_insights

    if days <= 0:
        raise click.UsageError("--days must be greater than zero")

    data = get_insights(days=days)

    if json_output:
        click.echo(json.dumps(data, indent=2))
        return

    if data["total_calls"] == 0:
        console.print("[dim]No API calls tracked yet.[/dim]")
        return

    conc = data["concentration"]
    lines = [
        f"[bold]Total cost:[/bold] ${data['total_cost_usd']:.4f}",
        f"[bold]API calls:[/bold] {data['total_calls']:,}",
    ]
    if conc["top_model"]:
        tm = conc["top_model"]
        lines.append(
            f"[bold]Top model:[/bold] {tm['model']} "
            f"(${tm['cost_usd']:.4f}, {tm['share'] * 100:.0f}% of spend)"
        )
    if conc["top_endpoint"]:
        te = conc["top_endpoint"]
        lines.append(f"[bold]Top endpoint:[/bold] {te['endpoint']} ({te['share'] * 100:.0f}%)")

    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title=f"[bold cyan]TokenTracker insights — last {days} days[/bold cyan]",
            border_style="cyan",
        )
    )

    if conc["dominated"] and conc["top_model"]:
        tm = conc["top_model"]
        console.print(
            f"\n[yellow]{tm['model']} is {tm['share'] * 100:.0f}% of your spend; "
            "a regression there moves the whole bill.[/yellow]"
        )

    if data["anomalies"]:
        console.print()
        t = Table(title="Spend anomalies", show_lines=False)
        t.add_column("Date", style="bold")
        t.add_column("Cost", justify="right", style="green")
        t.add_column("Baseline", justify="right", style="dim")
        t.add_column("Calls", justify="right")
        t.add_column("Above baseline", justify="right", style="red")
        for a in data["anomalies"]:
            t.add_row(
                a["date"],
                f"${a['cost_usd']:.4f}",
                f"${a['baseline_usd']:.4f}",
                str(a["calls"]),
                f"{a['z_score']:.1f}σ",
            )
        console.print(t)

    if data["suggestions"]:
        console.print("\n[bold]Suggestions[/bold]")
        for sg in data["suggestions"]:
            console.print(f"  - {sg['message']}")

    if not data["anomalies"] and not conc["dominated"] and not data["suggestions"]:
        console.print("\n[dim]Nothing notable: no anomalies, concentration or savings found.[/dim]")


@main.command()
@click.option("--format", "-f", "fmt", type=click.Choice(["json", "csv"]), default="json")
@click.option("--days", "-d", default=30)
def export(fmt: str, days: int):
    """Export usage data to JSON or CSV."""
    import csv

    from tokentracker.query import recent as get_recent

    calls = get_recent(limit=10000, days=days)
    if not calls:
        console.print("[dim]No data to export.[/dim]")
        return

    if fmt == "json":
        click.echo(json.dumps(calls, indent=2, default=str))
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=calls[0].keys())
        writer.writeheader()
        writer.writerows(calls)
