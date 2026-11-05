"""Yash Engineering seller profile transcribed from customer-provided quotations.

Defaults may be changed per quotation by a permitted estimator/commercial user.
Historical customer contact names and historical prices are NEVER defaults.
"""
from __future__ import annotations
import copy

YASH_BRANDING = {
    'name': 'YASH ENGINEERING',
    # Quote 73 office and works address, including the original wording.
    'address': 'Flat-603 Mangalmurti Aparment Chaudhari Park Lane No 9, Dighi,Pune 411015.',
    'works_address': 'Gat No. 255 Jyotiba Nagar, Talwade.',
    'gstin': '27JILPS1079H1ZL',
    'contact': 'yashengineering2912@gmail.com | 9423585573 / 9309884127',
    'signature_title': 'Proprietor',
}


def fresh_branding():
    return copy.deepcopy(YASH_BRANDING)
