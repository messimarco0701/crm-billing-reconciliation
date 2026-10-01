"""
Generates a synthetic dataset that mimics a CRM export and a billing system export.

Everything here is fake. Company names, VAT numbers and amounts are random,
but the shape of the data and the kind of mistakes injected into it come from
what you actually see when two systems are filled in by different people.

The script also writes data/injected_anomalies.csv: the list of problems we
planted on purpose. The test suite uses it to check that the reconciliation
finds all of them and nothing else.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from faker import Faker

SEED = 42
N_COMPANIES = 320
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

SECTORS = [
    "Logistica", "Meccanica", "Alimentari", "Costruzioni", "Consulting",
    "Trasporti", "Plastica", "Tessile", "Software", "Impianti", "Farmaceutica",
    "Arredamenti", "Energia", "Servizi", "Packaging", "Elettronica",
]
SUFFIXES = ["S.r.l.", "S.p.A.", "S.r.l.s.", "S.n.c."]
PRODUCTS = ["Flex", "Core", "Premium"]
CHANNELS = ["Direct", "Partner", "Referral"]
PARTNERS = ["Studio Aurora", "Consulenti Riuniti", "Rete Imprese Nord", "Paghe & Co"]
OWNERS = ["Giulia R.", "Luca M.", "Sara B.", "Andrea T.", "Elena F."]
OPEN_STAGES = ["Negotiation", "Contract Sent", "Discovery"]

fake = Faker("it_IT")
Faker.seed(SEED)
rng = random.Random(SEED)


def short_name(name: str) -> str:
    """Name used inside deal names: upper case, no legal suffix."""
    for s in sorted(SUFFIXES, key=len, reverse=True):
        name = name.replace(s, "")
    return " ".join(name.upper().split())


def messy_name(name: str) -> str:
    """The same company, typed by a human in a hurry."""
    variants = [
        lambda n: n.upper(),
        lambda n: n.lower(),
        lambda n: n.replace("S.r.l.", "SRL").replace("S.p.A.", "spa"),
        lambda n: "  ".join(n.split()),
        lambda n: n.replace("S.r.l.", "srl").replace(" ", "  ", 1),
    ]
    return rng.choice(variants)(name)


def typo(name: str) -> str:
    """Swap two adjacent letters somewhere in the middle of the name."""
    i = rng.randint(2, max(3, len(name) // 2))
    return name[:i] + name[i + 1] + name[i] + name[i + 2:]


def messy_vat(vat: str) -> str:
    return rng.choice([vat, f"IT{vat}", f"IT {vat}", f"{vat[:5]} {vat[5:]}", f" {vat} "])


def random_fee() -> float:
    # Skewed distribution: many small customers, a few large ones
    return round(min(rng.lognormvariate(8.6, 0.8), 90_000), -1) + 1_500


def build_companies() -> list[dict]:
    companies, seen_names, seen_vats = [], set(), set()
    while len(companies) < N_COMPANIES:
        name = f"{fake.last_name()} {rng.choice(SECTORS)} {rng.choice(SUFFIXES)}"
        vat = "".join(str(rng.randint(0, 9)) for _ in range(11))
        if short_name(name) in seen_names or vat in seen_vats:
            continue
        seen_names.add(short_name(name))
        seen_vats.add(vat)
        companies.append({"name": name, "vat": vat, "city": fake.city()})
    return companies


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    companies = build_companies()

    deals, contracts, plan_lines, truth = [], [], [], []
    deal_seq, contract_seq = 1000, 5000

    # Roughly two out of three deals are won and become a contract
    won = [c for c in companies if rng.random() < 0.68]
    lost_or_open = [c for c in companies if c not in won]

    # Pick disjoint groups of won companies to carry exactly one planted problem each
    pool = won[:]
    rng.shuffle(pool)
    plan = {
        "missing_in_billing": 10,
        "amount_mismatch": 12,
        "stage_mismatch": 6,
        "no_billing_plan": 5,
        "plan_total_mismatch": 6,
        "below_minimum_fee": 5,
        "deal_name_format": 8,
        "duplicate_vat": 4,
        "missing_vat": 10,
    }
    groups = {}
    for kind, n in plan.items():
        groups[kind], pool = pool[:n], pool[n:]
    flagged = {c["vat"]: kind for kind, group in groups.items() for c in group}

    def add_truth(vat: str, kind: str) -> None:
        truth.append({"vat": vat, "anomaly_type": kind})

    for c in won:
        kind = flagged.get(c["vat"])
        product = rng.choice(PRODUCTS)
        fee = random_fee()
        if kind == "below_minimum_fee":
            fee = float(rng.randrange(400, 1_100, 10))
        close = date(2025, 1, 1) + timedelta(days=rng.randint(0, 360))
        channel = rng.choice(CHANNELS)

        crm_amount = fee
        if kind == "amount_mismatch":
            crm_amount = round(fee * rng.choice([0.7, 0.85, 1.15, 1.3, 2.0]), 2)
        elif rng.random() < 0.15:
            # Rounding noise that should stay below the tolerance and not be flagged
            crm_amount = round(fee * rng.uniform(0.995, 1.005), 2)

        deal_name = f"{short_name(c['name'])} | {product.upper()} | {close.year}"
        if kind == "deal_name_format":
            deal_name = rng.choice([
                deal_name.lower(),
                deal_name.replace(" | ", " - "),
                f"{short_name(c['name'])} | {product.upper()}",
                f"{c['name']} {product}",
            ])

        stage = rng.choice(OPEN_STAGES) if kind == "stage_mismatch" else "Closed Won"
        vat_in_crm = "" if kind == "missing_vat" else messy_vat(c["vat"])
        if kind == "missing_vat":
            crm_name = typo(c["name"]) if rng.random() < 0.5 else messy_name(c["name"])
        else:
            crm_name = messy_name(c["name"]) if rng.random() < 0.3 else c["name"]

        deal_seq += 1
        deals.append({
            "deal_id": f"D{deal_seq}", "deal_name": deal_name, "company_name": crm_name,
            "vat_number": vat_in_crm, "channel": channel,
            "partner_name": rng.choice(PARTNERS) if channel == "Partner" else "",
            "stage": stage, "amount": crm_amount, "close_date": close.isoformat(),
            "owner": rng.choice(OWNERS),
        })

        if kind == "duplicate_vat":
            # Somebody created the same customer twice with a slightly different name
            deal_seq += 1
            dup = dict(deals[-1])
            dup.update({"deal_id": f"D{deal_seq}", "company_name": messy_name(c["name"]),
                        "vat_number": messy_vat(c["vat"]), "owner": rng.choice(OWNERS)})
            deals.append(dup)

        if kind:
            add_truth(c["vat"], kind)

        if kind == "missing_in_billing":
            continue

        contract_seq += 1
        cid = f"C{contract_seq}"
        start = close + timedelta(days=rng.randint(5, 40))
        contracts.append({
            "contract_id": cid, "customer_name": c["name"], "vat_number": c["vat"],
            "product": product, "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=364)).isoformat(),
            "annual_fee": fee, "status": "Active", "city": c["city"],
        })

        if kind == "no_billing_plan":
            continue
        quarters = [round(fee / 4, 2)] * 3
        quarters.append(round(fee - sum(quarters), 2))
        if kind == "plan_total_mismatch":
            quarters.pop(rng.randrange(4))
        for q, amount in enumerate(quarters):
            plan_lines.append({
                "plan_line_id": f"{cid}-{q + 1}", "contract_id": cid,
                "due_date": (start + timedelta(days=91 * q)).isoformat(), "amount": amount,
            })

    for c in lost_or_open:
        deal_seq += 1
        close = date(2025, 1, 1) + timedelta(days=rng.randint(0, 360))
        product = rng.choice(PRODUCTS)
        channel = rng.choice(CHANNELS)
        deals.append({
            "deal_id": f"D{deal_seq}",
            "deal_name": f"{short_name(c['name'])} | {product.upper()} | {close.year}",
            "company_name": c["name"], "vat_number": messy_vat(c["vat"]), "channel": channel,
            "partner_name": rng.choice(PARTNERS) if channel == "Partner" else "",
            "stage": rng.choice(["Closed Lost", "Closed Lost"] + OPEN_STAGES),
            "amount": random_fee(), "close_date": close.isoformat(), "owner": rng.choice(OWNERS),
        })

    # Contracts that exist in billing but were never tracked in the CRM
    for _ in range(6):
        name = f"{fake.last_name()} {rng.choice(SECTORS)} {rng.choice(SUFFIXES)}"
        vat = "".join(str(rng.randint(0, 9)) for _ in range(11))
        contract_seq += 1
        cid = f"C{contract_seq}"
        fee = random_fee()
        start = date(2025, 1, 1) + timedelta(days=rng.randint(0, 300))
        contracts.append({
            "contract_id": cid, "customer_name": name, "vat_number": vat,
            "product": rng.choice(PRODUCTS), "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=364)).isoformat(),
            "annual_fee": fee, "status": "Active", "city": fake.city(),
        })
        for q in range(4):
            plan_lines.append({"plan_line_id": f"{cid}-{q + 1}", "contract_id": cid,
                               "due_date": (start + timedelta(days=91 * q)).isoformat(),
                               "amount": round(fee / 4, 2)})
        add_truth(vat, "missing_in_crm")

    rng.shuffle(deals)
    pd.DataFrame(deals).to_csv(DATA_DIR / "crm_deals.csv", index=False)
    pd.DataFrame(contracts).to_csv(DATA_DIR / "billing_contracts.csv", index=False)
    pd.DataFrame(plan_lines).to_csv(DATA_DIR / "billing_plan_lines.csv", index=False)
    pd.DataFrame(truth).sort_values(["anomaly_type", "vat"]).to_csv(
        DATA_DIR / "injected_anomalies.csv", index=False)

    print(f"CRM deals:          {len(deals)}")
    print(f"Billing contracts:  {len(contracts)}")
    print(f"Billing plan lines: {len(plan_lines)}")
    print(f"Planted anomalies:  {len(truth)}")


if __name__ == "__main__":
    main()
