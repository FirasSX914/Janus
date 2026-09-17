"""Un seul appel à Jev. Imprime la réponse brute, telle quelle.

Sert à constater la forme exacte de l'objet retourné avant d'écrire
quoi que ce soit qui en dépende.
"""

import os
from pathlib import Path

from typesafe_sdk import Choice, TypeSafeClient

for line in (Path(__file__).resolve().parent.parent / ".env").read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())

STATE = (
    "Bonjour, j'ai commandé une paire de chaussures il y a dix jours et le colis "
    "n'est toujours pas arrivé. Le suivi n'a pas bougé depuis mardi. "
    "Est-ce que vous pouvez me dire où il en est ?"
)

with TypeSafeClient() as client:
    response = client.system_one(
        state=STATE,
        model="jev-latest",
        questions={
            "department": Choice(
                instructions="Quelle équipe doit traiter ce message ?",
                criteria={
                    "shipping": "Suivi de commande, retard, colis perdu",
                    "billing": "Facturation, paiement, remboursement",
                },
            ),
        },
    )

print("--- corps HTTP brut ---")
print(response.raw_http_response.text)

print("--- objet SDK ---")
print(repr(response))

print("--- answers['department'] ---")
print(repr(response.answers["department"]))
