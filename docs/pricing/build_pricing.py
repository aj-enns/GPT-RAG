"""Generate the GPT-RAG production pricing workbook.

All calculations live as Excel formulas so the model recalculates when
inputs (chats/month, token sizes, sensitivity toggles, etc.) change.
Hardcoded blue cells = inputs, black = formulas.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName


OUTPUT = Path(__file__).resolve().parent / "GPT-RAG-Production-Cost-Model.xlsx"

FONT_NAME = "Arial"

# Color palette
BLUE_INPUT = Font(name=FONT_NAME, color="0000FF")
BLACK_FORMULA = Font(name=FONT_NAME, color="000000")
GREEN_LINK = Font(name=FONT_NAME, color="008000")
HEADER_FONT = Font(name=FONT_NAME, bold=True, color="FFFFFF")
SECTION_FONT = Font(name=FONT_NAME, bold=True, color="000000")
NOTE_FONT = Font(name=FONT_NAME, italic=True, color="595959", size=10)

HEADER_FILL = PatternFill("solid", start_color="003366")
SECTION_FILL = PatternFill("solid", start_color="D9E1F2")
TOTAL_FILL = PatternFill("solid", start_color="FFF2CC")
ASSUMPTION_FILL = PatternFill("solid", start_color="FFFFCC")

CURRENCY_FMT = '_($* #,##0.00_);_($* (#,##0.00);_($* "-"??_);_(@_)'
CURRENCY_INT_FMT = '_($* #,##0_);_($* (#,##0);_($* "-"_);_(@_)'
NUMBER_FMT = "#,##0"
PERCENT_FMT = "0.0%"

THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
RIGHT = Alignment(horizontal="right", vertical="center")


def apply_header(cell):
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.alignment = CENTER
    cell.border = BORDER


def apply_section(cell):
    cell.font = SECTION_FONT
    cell.fill = SECTION_FILL
    cell.alignment = LEFT
    cell.border = BORDER


def set_col_widths(ws, widths):
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width


# ---------------------------------------------------------------------------
# Workbook
# ---------------------------------------------------------------------------
wb = Workbook()

# ===========================================================================
# Sheet 1: Assumptions (inputs that drive everything)
# ===========================================================================
ws_a = wb.active
ws_a.title = "Assumptions"
ws_a.sheet_view.showGridLines = False

ws_a.merge_cells("A1:D1")
ws_a["A1"] = "GPT-RAG — Production Cost Assumptions"
ws_a["A1"].font = Font(name=FONT_NAME, bold=True, size=14, color="FFFFFF")
ws_a["A1"].fill = HEADER_FILL
ws_a["A1"].alignment = CENTER

ws_a["A3"] = "Parameter"
ws_a["B3"] = "Value"
ws_a["C3"] = "Source / Rationale"
ws_a["D3"] = "Sensitivity"
for col in "ABCD":
    apply_header(ws_a[f"{col}3"])

assumptions = [
    # (name, label, value, format, source, sensitivity, defined_name)
    ("region",    "Target region",                 "Canada Central", None,         "User selection",                                   "High",   None),
    ("network",   "Network posture",               "Zero Trust",     None,         "User selection",                                   "High",   None),
    ("contract",  "Contract type",                 "PAYG (no EA)",   None,         "User selection",                                   "High",   None),
    ("currency",  "Currency",                      "USD",            None,         "Pricing convention",                               "Med",    None),
    ("ri_term",   "Reservation term (compare)",    "1-year",         None,         "User selection",                                   "Med",    None),
    (None,        None,                            None,             None,         None,                                                None,     None),  # blank
    ("chats",     "Chats per month",               50000,            NUMBER_FMT,   "Medium-scale department workload",                 "High",   "ChatsPerMonth"),
    ("toks_in",   "Avg input tokens / chat",       3000,             NUMBER_FMT,   "System + RAG context + 2-3 turn history",          "High",   "TokensIn"),
    ("toks_out",  "Avg output tokens / chat",      500,              NUMBER_FMT,   "Typical RAG answer length",                        "Med",    "TokensOut"),
    ("corpus_gb", "Document corpus (GB raw)",      50,               NUMBER_FMT,   "User selection — medium scale",                    "Med",    "CorpusGB"),
    ("text_ratio","Text-to-raw ratio",             0.2,              PERCENT_FMT,  "OCR/extracted text ≈ 20% of raw mixed media",      "Low",    "TextRatio"),
    ("tok_per_kb","Embedding tokens per KB text",  250,              NUMBER_FMT,   "~4 chars/token, 1 KB ≈ 250 tokens",                "Low",    "TokPerKB"),
    ("refresh",   "Corpus refresh rate / month",   0.10,             PERCENT_FMT,  "Typical enterprise document churn",                "Low",    "RefreshRate"),
    (None,        None,                            None,             None,         None,                                                None,     None),
    ("aoai_in",   "gpt-4o input $/1K tokens",      0.0025,           CURRENCY_FMT, "Azure retail, GlobalStandard, mid-2026",           "High",   "AOAI_In"),
    ("aoai_out",  "gpt-4o output $/1K tokens",     0.010,            CURRENCY_FMT, "Azure retail, GlobalStandard, mid-2026",           "High",   "AOAI_Out"),
    ("emb_price", "embedding-3-large $/1K tokens", 0.00013,          CURRENCY_FMT, "Azure retail",                                     "Low",    "EmbPrice"),
    ("search_su", "AI Search S1 unit $/mo",        248.20,           CURRENCY_FMT, "Canada Central retail",                            "High",   "SearchUnit"),
    ("search_p",  "AI Search partitions",          2,                NUMBER_FMT,   "50 GB needs 2 × 25GB partitions",                  "High",   "SearchPartitions"),
    ("search_r",  "AI Search replicas (HA)",       2,                NUMBER_FMT,   "2 for query HA + indexing",                        "High",   "SearchReplicas"),
    ("semantic",  "Semantic ranker $/1K queries",  1.00,             CURRENCY_FMT, "Standard tier, first 1K free",                     "Low",    "SemanticPrice"),
    ("cosmos_ru", "Cosmos autoscale max RU/s",     10000,            NUMBER_FMT,   "Burst headroom for chat traffic",                  "Med",    "CosmosMaxRU"),
    ("cosmos_util","Cosmos avg utilization",       0.20,             PERCENT_FMT,  "Autoscale bills max(10% of max, used)",            "Med",    "CosmosUtil"),
    ("cosmos_p",  "Cosmos RU $/100 RU/hr",         0.012,            CURRENCY_FMT, "Autoscale standard rate",                          "Med",    "CosmosRUPrice"),
    ("aca_d4",    "Container Apps D4 profile $/mo",146.00,           CURRENCY_FMT, "Dedicated D4 profile, single instance",            "Med",    "ACA_D4"),
    ("acr_prem",  "Container Registry Premium $/mo",667.00,          CURRENCY_FMT, "REQUIRED for private endpoints",                    "High",   "ACR_Prem"),
    ("bastion",   "Azure Bastion Standard $/mo",   139.00,           CURRENCY_FMT, "Required for jump VM access (730 hr)",             "Med",    "Bastion"),
    ("vm_d2",     "Jump VM D2s_v3 $/mo PAYG",      70.00,            CURRENCY_FMT, "Linux, 730 hr",                                    "Low",    "VM_PAYG"),
    ("vm_disk",   "Jump VM disk + OS $/mo",        10.00,            CURRENCY_FMT, "P10 64GB premium SSD",                             "Low",    "VM_Disk"),
    ("pe_count",  "Private endpoints (count)",     12,               NUMBER_FMT,   "One per data-plane PaaS",                          "Low",    "PECount"),
    ("pe_price",  "Private endpoint $/mo each",    7.30,             CURRENCY_FMT, "Hosting + 10 GB processing typical",                "Low",    "PEPrice"),
    ("dns",       "Private DNS zones $/mo total",  6.00,             CURRENCY_FMT, "12 zones × $0.50",                                 "Low",    "DNSPrice"),
    ("storage",   "Storage Account $/mo",          15.00,            CURRENCY_FMT, "~60 GB blob LRS hot + transactions",               "Low",    "Storage"),
    ("appconfig", "App Configuration Std $/mo",    44.00,            CURRENCY_FMT, "Standard tier + PE",                               "Low",    "AppCfg"),
    ("keyvault",  "Key Vault Std $/mo",            10.00,            CURRENCY_FMT, "Operations + PE",                                  "Low",    "KV"),
    ("monitor",   "Log Analytics + App Insights $/mo",75.00,         CURRENCY_FMT, "~30 GB ingest PAYG",                               "Med",    "Monitor"),
    (None,        None,                            None,             None,         None,                                                None,     None),
    ("ri_search", "AI Search RI discount",         0.0,              PERCENT_FMT,  "Not available for AI Search",                      "Low",    "RI_Search"),
    ("ri_cosmos", "Cosmos 1-yr reserved discount", 0.20,             PERCENT_FMT,  "Typical 1-yr RC for Cosmos",                       "Low",    "RI_Cosmos"),
    ("ri_vm",     "VM 1-yr RI discount",           0.35,             PERCENT_FMT,  "D2s_v3 1-yr standard RI",                          "Low",    "RI_VM"),
    ("ri_aoai",   "AOAI PTU savings vs PAYG",      0.0,              PERCENT_FMT,  "PTU not viable at this TPM scale",                 "Med",    "RI_AOAI"),
]

row = 4
for item in assumptions:
    if item[0] is None:
        row += 1
        continue
    _, label, value, fmt, source, sens, defname = item
    ws_a[f"A{row}"] = label
    ws_a[f"A{row}"].font = Font(name=FONT_NAME, bold=True)
    ws_a[f"A{row}"].alignment = LEFT

    cell = ws_a[f"B{row}"]
    cell.value = value
    cell.font = BLUE_INPUT
    cell.fill = ASSUMPTION_FILL
    cell.alignment = RIGHT
    cell.border = BORDER
    if fmt:
        cell.number_format = fmt

    ws_a[f"C{row}"] = source
    ws_a[f"C{row}"].alignment = LEFT
    ws_a[f"C{row}"].font = Font(name=FONT_NAME, size=10, color="595959")

    ws_a[f"D{row}"] = sens
    ws_a[f"D{row}"].alignment = CENTER
    ws_a[f"D{row}"].font = Font(name=FONT_NAME, size=10, color="595959")

    if defname:
        ref = f"Assumptions!${'B'}${row}"
        wb.defined_names[defname] = DefinedName(name=defname, attr_text=ref)
    row += 1

set_col_widths(ws_a, [38, 18, 55, 12])
ws_a.freeze_panes = "A4"


# ===========================================================================
# Sheet 2: Cost Summary
# ===========================================================================
ws_s = wb.create_sheet("Cost Summary")
ws_s.sheet_view.showGridLines = False

ws_s.merge_cells("A1:G1")
ws_s["A1"] = "GPT-RAG — Monthly & Annual Cost Summary (Canada Central, Zero Trust)"
ws_s["A1"].font = Font(name=FONT_NAME, bold=True, size=14, color="FFFFFF")
ws_s["A1"].fill = HEADER_FILL
ws_s["A1"].alignment = CENTER

headers = ["Service", "SKU / Config", "Monthly PAYG ($)", "Monthly 1-yr ($)",
           "Annual PAYG ($)", "Annual 1-yr ($)", "Optimization Note"]
for i, h in enumerate(headers, start=1):
    c = ws_s.cell(row=3, column=i, value=h)
    apply_header(c)

# Each row: service, sku, monthly PAYG formula, monthly 1yr formula, notes
# We reference defined names from Assumptions.
service_rows = [
    (
        "Azure OpenAI — chat (gpt-4o)",
        "GlobalStandard, PAYG",
        # Monthly: chats * ((in/1000)*price_in + (out/1000)*price_out)
        "=ChatsPerMonth*((TokensIn/1000)*AOAI_In + (TokensOut/1000)*AOAI_Out)",
        "=C4*(1-RI_AOAI)",
        "Token-priced; PTU not economical < ~150K chats/mo",
    ),
    (
        "Azure OpenAI — embeddings",
        "text-embedding-3-large",
        # Monthly tokens: corpus_GB * 1024*1024 KB * text_ratio * tok_per_KB * refresh
        "=(CorpusGB*1024*1024*TextRatio*TokPerKB*RefreshRate/1000)*EmbPrice",
        "=C5",
        "One-time initial load not included; see Sensitivity sheet",
    ),
    (
        "Azure AI Search",
        "Standard S1, 2 partitions × 2 replicas",
        "=SearchUnit*SearchPartitions*SearchReplicas",
        "=C6*(1-RI_Search)",
        "No RI offered; right-size partitions/replicas to cut cost",
    ),
    (
        "Azure AI Search — semantic ranker",
        "Per-query, S1",
        "=MAX(0,(ChatsPerMonth-1000))/1000*SemanticPrice",
        "=C7",
        "First 1K queries/mo free",
    ),
    (
        "Cosmos DB",
        "Autoscale 1K–10K RU/s",
        # bill = max(10% of max, util*max) * 730 hr * price/100RU
        "=MAX(CosmosMaxRU*0.1, CosmosMaxRU*CosmosUtil)*730*CosmosRUPrice/100",
        "=C8*(1-RI_Cosmos)",
        "1-yr RC saves ~20%; consider serverless if usage <30%",
    ),
    (
        "Container Apps (D4 profile)",
        "Dedicated D4, 1 instance",
        "=ACA_D4",
        "=C9",
        "Hosts orchestrator/frontend/dataingest/mcp on shared profile",
    ),
    (
        "Container Registry",
        "Premium (REQUIRED for PE)",
        "=ACR_Prem",
        "=C10",
        "Standard ($20) is NOT an option under Zero Trust",
    ),
    (
        "Azure Bastion",
        "Standard, 730 hr",
        "=Bastion",
        "=C11",
        "Required for jump VM access; remove if VM removed",
    ),
    (
        "Jump VM",
        "D2s_v3 + P10 disk",
        "=VM_PAYG+VM_Disk",
        "=VM_PAYG*(1-RI_VM)+VM_Disk",
        "1-yr RI ~35% off; consider auto-shutdown",
    ),
    (
        "Private Endpoints",
        "~12 endpoints",
        "=PECount*PEPrice",
        "=C13",
        "One per data-plane PaaS",
    ),
    (
        "Storage Account",
        "Blob Standard LRS, ~60 GB",
        "=Storage",
        "=C14",
        "Documents, images, conversation cache",
    ),
    (
        "App Configuration",
        "Standard + PE",
        "=AppCfg",
        "=C15",
        "Centralized runtime config",
    ),
    (
        "Key Vault",
        "Standard + PE",
        "=KV",
        "=C16",
        "Secret operations",
    ),
    (
        "Monitor (Log Analytics + AI)",
        "Pay-as-you-go ingestion",
        "=Monitor",
        "=C17",
        "~30 GB/mo telemetry — cap with daily limit",
    ),
    (
        "Private DNS zones",
        "~12 zones",
        "=DNSPrice",
        "=C18",
        "Negligible",
    ),
]

start_row = 4
for i, (svc, sku, payg, ri, note) in enumerate(service_rows):
    r = start_row + i
    ws_s.cell(row=r, column=1, value=svc).alignment = LEFT
    ws_s.cell(row=r, column=2, value=sku).alignment = LEFT
    ws_s.cell(row=r, column=3, value=payg)
    ws_s.cell(row=r, column=4, value=ri)
    ws_s.cell(row=r, column=5, value=f"=C{r}*12")
    ws_s.cell(row=r, column=6, value=f"=D{r}*12")
    ws_s.cell(row=r, column=7, value=note).alignment = LEFT
    for col in (3, 4, 5, 6):
        ws_s.cell(row=r, column=col).number_format = CURRENCY_INT_FMT
        ws_s.cell(row=r, column=col).font = BLACK_FORMULA
        ws_s.cell(row=r, column=col).alignment = RIGHT
        ws_s.cell(row=r, column=col).border = BORDER
    ws_s.cell(row=r, column=7).font = Font(name=FONT_NAME, size=10, color="595959")

# Totals row
total_row = start_row + len(service_rows)
ws_s.cell(row=total_row, column=1, value="TOTAL").font = Font(name=FONT_NAME, bold=True)
ws_s.cell(row=total_row, column=2, value="").fill = TOTAL_FILL
for col in (3, 4, 5, 6):
    letter = get_column_letter(col)
    c = ws_s.cell(
        row=total_row,
        column=col,
        value=f"=SUM({letter}{start_row}:{letter}{total_row - 1})",
    )
    c.font = Font(name=FONT_NAME, bold=True)
    c.fill = TOTAL_FILL
    c.number_format = CURRENCY_INT_FMT
    c.alignment = RIGHT
    c.border = BORDER
ws_s.cell(row=total_row, column=1).fill = TOTAL_FILL
ws_s.cell(row=total_row, column=7).fill = TOTAL_FILL

# Headline KPI rows
kpi_row = total_row + 2
ws_s.cell(row=kpi_row, column=1, value="Monthly PAYG total").font = SECTION_FONT
ws_s.cell(row=kpi_row, column=3, value=f"=C{total_row}").number_format = CURRENCY_INT_FMT
ws_s.cell(row=kpi_row, column=3).font = Font(name=FONT_NAME, bold=True, color="C00000")
ws_s.cell(row=kpi_row, column=3).alignment = RIGHT

ws_s.cell(row=kpi_row + 1, column=1, value="Annual PAYG total").font = SECTION_FONT
ws_s.cell(row=kpi_row + 1, column=3, value=f"=E{total_row}").number_format = CURRENCY_INT_FMT
ws_s.cell(row=kpi_row + 1, column=3).font = Font(name=FONT_NAME, bold=True, color="C00000")
ws_s.cell(row=kpi_row + 1, column=3).alignment = RIGHT

ws_s.cell(row=kpi_row + 2, column=1, value="Annual savings vs PAYG (1-yr commitments)").font = SECTION_FONT
ws_s.cell(row=kpi_row + 2, column=3, value=f"=E{total_row}-F{total_row}").number_format = CURRENCY_INT_FMT
ws_s.cell(row=kpi_row + 2, column=3).font = Font(name=FONT_NAME, bold=True, color="00B050")
ws_s.cell(row=kpi_row + 2, column=3).alignment = RIGHT

ws_s.cell(row=kpi_row + 3, column=1, value="Savings %").font = SECTION_FONT
ws_s.cell(row=kpi_row + 3, column=3, value=f"=(E{total_row}-F{total_row})/E{total_row}").number_format = PERCENT_FMT
ws_s.cell(row=kpi_row + 3, column=3).font = Font(name=FONT_NAME, bold=True, color="00B050")
ws_s.cell(row=kpi_row + 3, column=3).alignment = RIGHT

set_col_widths(ws_s, [34, 36, 16, 16, 16, 16, 44])
ws_s.freeze_panes = "A4"
ws_s.auto_filter.ref = f"A3:G{total_row - 1}"


# ===========================================================================
# Sheet 3: Detailed Breakdown (dimensions per service)
# ===========================================================================
ws_d = wb.create_sheet("Detailed Breakdown")
ws_d.sheet_view.showGridLines = False

ws_d.merge_cells("A1:F1")
ws_d["A1"] = "Cost Dimension Breakdown"
ws_d["A1"].font = Font(name=FONT_NAME, bold=True, size=14, color="FFFFFF")
ws_d["A1"].fill = HEADER_FILL
ws_d["A1"].alignment = CENTER

headers_d = ["Service", "Dimension", "Unit", "Unit Price ($)", "Est. Qty / mo", "Monthly Cost ($)"]
for i, h in enumerate(headers_d, start=1):
    apply_header(ws_d.cell(row=3, column=i, value=h))

detail_rows = [
    # service, dimension, unit, price formula, qty formula, monthly formula
    ("Azure OpenAI — chat", "Compute (input tokens)", "1K input tokens",
     "=AOAI_In", "=ChatsPerMonth*TokensIn/1000", "=D4*E4"),
    ("Azure OpenAI — chat", "Compute (output tokens)", "1K output tokens",
     "=AOAI_Out", "=ChatsPerMonth*TokensOut/1000", "=D5*E5"),
    ("Azure OpenAI — embeddings", "Compute (tokens)", "1K tokens",
     "=EmbPrice", "=CorpusGB*1024*1024*TextRatio*TokPerKB*RefreshRate/1000", "=D6*E6"),
    ("Azure AI Search", "Compute (search units)", "S1 SU / mo",
     "=SearchUnit", "=SearchPartitions*SearchReplicas", "=D7*E7"),
    ("Azure AI Search", "Transactions (semantic)", "1K queries",
     "=SemanticPrice", "=MAX(0,(ChatsPerMonth-1000))/1000", "=D8*E8"),
    ("Cosmos DB", "Compute (RU/s)", "100 RU/hr",
     "=CosmosRUPrice", "=MAX(CosmosMaxRU*0.1, CosmosMaxRU*CosmosUtil)*730/100", "=D9*E9"),
    ("Container Apps", "Compute (workload profile)", "D4 profile / mo",
     "=ACA_D4", 1, "=D10*E10"),
    ("Container Registry", "Hosting", "Premium / mo",
     "=ACR_Prem", 1, "=D11*E11"),
    ("Azure Bastion", "Hosting", "Std / mo",
     "=Bastion", 1, "=D12*E12"),
    ("Jump VM", "Compute", "D2s_v3 / mo",
     "=VM_PAYG", 1, "=D13*E13"),
    ("Jump VM", "Storage", "P10 disk / mo",
     "=VM_Disk", 1, "=D14*E14"),
    ("Networking", "Private Endpoints", "PE / mo",
     "=PEPrice", "=PECount", "=D15*E15"),
    ("Networking", "Private DNS zones", "Total / mo",
     "=DNSPrice", 1, "=D16*E16"),
    ("Storage Account", "Storage + transactions", "Blob LRS / mo",
     "=Storage", 1, "=D17*E17"),
    ("App Configuration", "Hosting", "Std / mo",
     "=AppCfg", 1, "=D18*E18"),
    ("Key Vault", "Operations", "Std / mo",
     "=KV", 1, "=D19*E19"),
    ("Monitor", "Ingestion (Log Analytics + App Insights)", "PAYG / mo",
     "=Monitor", 1, "=D20*E20"),
]

start = 4
for i, row in enumerate(detail_rows):
    r = start + i
    for c_idx, val in enumerate(row, start=1):
        cell = ws_d.cell(row=r, column=c_idx, value=val)
        cell.border = BORDER
        cell.font = BLACK_FORMULA
        if c_idx in (1, 2, 3):
            cell.alignment = LEFT
        else:
            cell.alignment = RIGHT
    ws_d.cell(row=r, column=4).number_format = CURRENCY_FMT
    ws_d.cell(row=r, column=5).number_format = "#,##0.0"
    ws_d.cell(row=r, column=6).number_format = CURRENCY_INT_FMT

# Total
tr = start + len(detail_rows)
ws_d.cell(row=tr, column=1, value="TOTAL Monthly").font = Font(name=FONT_NAME, bold=True)
ws_d.cell(row=tr, column=6, value=f"=SUM(F{start}:F{tr-1})").font = Font(name=FONT_NAME, bold=True)
ws_d.cell(row=tr, column=6).number_format = CURRENCY_INT_FMT
ws_d.cell(row=tr, column=6).fill = TOTAL_FILL
ws_d.cell(row=tr, column=1).fill = TOTAL_FILL
ws_d.cell(row=tr, column=6).alignment = RIGHT

set_col_widths(ws_d, [28, 36, 22, 16, 18, 18])
ws_d.freeze_panes = "A4"


# ===========================================================================
# Sheet 4: Sensitivity / Scenarios
# ===========================================================================
ws_x = wb.create_sheet("Sensitivity")
ws_x.sheet_view.showGridLines = False

ws_x.merge_cells("A1:D1")
ws_x["A1"] = "Sensitivity & Scenario Analysis"
ws_x["A1"].font = Font(name=FONT_NAME, bold=True, size=14, color="FFFFFF")
ws_x["A1"].fill = HEADER_FILL
ws_x["A1"].alignment = CENTER

ws_x["A3"] = "Scenario / Lever"
ws_x["B3"] = "Monthly Δ ($)"
ws_x["C3"] = "Annual Δ ($)"
ws_x["D3"] = "Notes"
for col in "ABCD":
    apply_header(ws_x[f"{col}3"])

# baseline monthly = Cost Summary total
baseline = "'Cost Summary'!C19"  # total_row was start_row+len(service_rows) = 4+15 = 19

sensitivity = [
    ("Switch chat model to gpt-5.4-nano (current default)",
     # ~95% cheaper per token. Use 0.05 multiplier on chat line
     # Δ = -(chat_payg * 0.95)
     "=-(ChatsPerMonth*((TokensIn/1000)*AOAI_In+(TokensOut/1000)*AOAI_Out)*0.95)",
     None,
     "gpt-5.4-nano is ~$0.00015 in / $0.0006 out per 1K — ~95% reduction"),

    ("Drop to Standalone (no Zero Trust)",
     # Remove: ACR_Prem - $20 Basic, Bastion, VM+disk, all PEs, App Cfg PE delta ($0 - simplification)
     "=-(ACR_Prem-20) - Bastion - (VM_PAYG+VM_Disk) - PECount*PEPrice",
     None,
     "Premium ACR -> Basic; no Bastion/VM/PEs; keep all PaaS public + RBAC"),

    ("AI Search: 1 partition × 1 replica (no HA)",
     "=-SearchUnit*(SearchPartitions*SearchReplicas - 1)",
     None,
     "Removes query HA and indexing concurrency — pilot/POC only"),

    ("Add Azure Firewall Standard",
     "=910",
     None,
     "Some ZT patterns front-end with Firewall (730 hr * $1.25)"),

    ("Scale chats 10× (500K/mo)",
     "=ChatsPerMonth*9*((TokensIn/1000)*AOAI_In+(TokensOut/1000)*AOAI_Out) + MAX(0,(ChatsPerMonth*10-1000)-(ChatsPerMonth-1000))/1000*SemanticPrice",
     None,
     "AOAI becomes dominant; consider PTU re-evaluation"),

    ("Enable Bing Grounding (50K queries/mo)",
     "=50*7",
     None,
     "$7 per 1K transactions × 50K"),

    ("Initial corpus embedding load (one-time)",
     "=(CorpusGB*1024*1024*TextRatio*TokPerKB/1000)*EmbPrice",
     None,
     "One-time cost — not recurring; shown for budgeting"),

    ("10% EA discount on AOAI + Cosmos",
     "=-0.1*(ChatsPerMonth*((TokensIn/1000)*AOAI_In+(TokensOut/1000)*AOAI_Out) + MAX(CosmosMaxRU*0.1, CosmosMaxRU*CosmosUtil)*730*CosmosRUPrice/100)",
     None,
     "Typical EA discount; verify with your contract"),
]

r = 4
for label, monthly, _, note in sensitivity:
    ws_x.cell(row=r, column=1, value=label).alignment = LEFT
    c = ws_x.cell(row=r, column=2, value=monthly)
    c.number_format = CURRENCY_INT_FMT
    c.font = BLACK_FORMULA
    c.alignment = RIGHT
    c.border = BORDER
    c2 = ws_x.cell(row=r, column=3, value=f"=B{r}*12")
    c2.number_format = CURRENCY_INT_FMT
    c2.font = BLACK_FORMULA
    c2.alignment = RIGHT
    c2.border = BORDER
    ws_x.cell(row=r, column=4, value=note).alignment = LEFT
    ws_x.cell(row=r, column=4).font = Font(name=FONT_NAME, size=10, color="595959")
    r += 1

# Scenario totals
r += 1
ws_x.cell(row=r, column=1, value="Baseline monthly (Zero Trust, gpt-4o, 50K chats)").font = SECTION_FONT
ws_x.cell(row=r, column=2, value=f"={baseline}").number_format = CURRENCY_INT_FMT
ws_x.cell(row=r, column=2).alignment = RIGHT

r += 1
ws_x.cell(row=r, column=1, value="If you applied: nano + Standalone + 1×1 Search").font = SECTION_FONT
combo = "=-(ChatsPerMonth*((TokensIn/1000)*AOAI_In+(TokensOut/1000)*AOAI_Out)*0.95) - (ACR_Prem-20) - Bastion - (VM_PAYG+VM_Disk) - PECount*PEPrice - SearchUnit*(SearchPartitions*SearchReplicas-1)"
ws_x.cell(row=r, column=2, value=f"={baseline} + ({combo})").number_format = CURRENCY_INT_FMT
ws_x.cell(row=r, column=2).fill = TOTAL_FILL
ws_x.cell(row=r, column=2).font = Font(name=FONT_NAME, bold=True, color="00B050")
ws_x.cell(row=r, column=2).alignment = RIGHT

set_col_widths(ws_x, [50, 16, 16, 60])
ws_x.freeze_panes = "A4"


# ===========================================================================
# Sheet 5: Caveats
# ===========================================================================
ws_n = wb.create_sheet("Caveats & Notes")
ws_n.sheet_view.showGridLines = False

ws_n.merge_cells("A1:B1")
ws_n["A1"] = "Caveats, Exclusions, and Methodology"
ws_n["A1"].font = Font(name=FONT_NAME, bold=True, size=14, color="FFFFFF")
ws_n["A1"].fill = HEADER_FILL
ws_n["A1"].alignment = CENTER

ws_n["A3"] = "Topic"
ws_n["B3"] = "Detail"
apply_header(ws_n["A3"])
apply_header(ws_n["B3"])

caveats = [
    ("Pricing source", "Representative Azure retail rates for Canada Central as of mid-2026. No live Pricing API call was made. Verify with the Azure Pricing Calculator before any customer-facing commitment."),
    ("Currency & contract", "All figures USD, retail pay-as-you-go. Excludes EA / CSP / negotiated discounts (typically 10–20% on AOAI and Cosmos)."),
    ("Tax", "Excludes GST/HST. Add 13% (Ontario) or jurisdiction-equivalent for landed cost."),
    ("Egress", "Excludes data egress. Add ~$0.087/GB after 100 GB/mo free. Materially impacts cost if frontend serves users outside Canada."),
    ("AOAI PTU", "PTU pricing not modeled — workload sits well below the 15-PTU minimum for gpt-4o GlobalStandard. Re-evaluate above ~150K chats/mo sustained."),
    ("Embedding load", "Monthly embedding cost assumes 10% corpus refresh. One-time initial load is in the Sensitivity sheet as a separate line."),
    ("Reservations", "AI Search has no RI. Cosmos uses 20% reserved capacity discount. Jump VM uses 35% 1-yr RI. AOAI savings = 0 (no PTU at this scale)."),
    ("Network posture", "Zero Trust assumed: Premium ACR, Bastion, jump VM, ~12 private endpoints, private DNS zones. Standalone removes ~$1,500/mo (see Sensitivity)."),
    ("Component repos", "Per manifest.json: gpt-rag-ui v2.3.2, gpt-rag-orchestrator feature/architecture-advisor, gpt-rag-ingestion feature/architecture-advisor. Containers run on shared D4 workload profile."),
    ("Recalculation", "All values are Excel formulas referencing the Assumptions sheet. Change any blue input cell and totals recalculate."),
    ("Caveat on Search SKU", "S1 baseline used (768 MB partition, 50 GB storage per partition). For >100 GB or >25 indexes, evaluate S2 or L1."),
    ("Bing Grounding", "Disabled in current main.parameters.json (deployGroundingWithBing=false). If enabled, see Sensitivity line."),
]

r = 4
for topic, detail in caveats:
    ws_n.cell(row=r, column=1, value=topic).font = Font(name=FONT_NAME, bold=True)
    ws_n.cell(row=r, column=1).alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
    ws_n.cell(row=r, column=2, value=detail).alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
    ws_n.cell(row=r, column=1).border = BORDER
    ws_n.cell(row=r, column=2).border = BORDER
    ws_n.row_dimensions[r].height = 32
    r += 1

set_col_widths(ws_n, [22, 110])
ws_n.freeze_panes = "A4"


# Order sheets: Summary first
wb.move_sheet(ws_s, offset=-1)

wb.save(OUTPUT)
print(f"Wrote {OUTPUT}")
