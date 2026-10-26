"""Fragmente scurte de lore verificat, selectate lexical numai la cerere.

Surse Riot (fără wiki/fan theories):
https://nexus.leagueoflegends.com/en-us/2017/12/ask-riot-urf/
https://universe.leagueoflegends.com/en_US/region/freljord/
https://www.leagueoflegends.com/en-us/champions/braum/
https://www.leagueoflegends.com/ro-ro/news/tags/poro/
https://nexus.leagueoflegends.com/en-pl/2018/08/will-tribunal-return/
https://nexus.leagueoflegends.com/en-gb/2019/01/ask-riot-does-sion-stink/

Personalitatea acestui Poro este alegerea proiectului, nu o afirmație canonică.
"""

import re
import unicodedata


_LORE = (
    (("what are you", "who are you", "what is a poro", "about poro", "poros", "ce este un poro"),
     "I am a Poro: a tiny, magical, fluffy creature from the Freljord. Poro-Snax are our favorite treats!"),
    (("freljord", "where are you from", "your home", "snow", "cold", "runeterra"),
     "The Freljord is my home: an icy region in Runeterra filled with snow and ancient legends."),
    (("poro-snax", "poro snax", "snack", "food", "hungry", "delicious", "eat"),
     "Poro-Snax are made with Freljordian herbs and Avarosan poultry; Poros love them warm!"),
    (("braum",),
     "Braum is our kind-hearted hero in the Freljord, famous for his big shield and mustache!"),
    (("group of poros", "fluft", "cuddle", "fluffy", "fur"),
     "A group of Poros is called a fluft! People in the Freljord love cuddling with Poros to stay warm."),
)


def _normalize(value):
    value = "".join(ch for ch in unicodedata.normalize("NFD", value.casefold())
                    if unicodedata.category(ch) != "Mn")
    return " ".join(re.findall(r"[a-z0-9-]+", value))


def relevant_lore(question, max_chars=280):
    """Întoarce cel mult două fragmente relevante; cost constant, fără model/DB."""
    if not isinstance(question, str) or max_chars < 1:
        return ""
    plain = _normalize(question)
    selected = []
    for triggers, fact in _LORE:
        if any(re.search(r"(?<![a-z0-9])" + re.escape(trigger) + r"(?![a-z0-9])", plain)
               for trigger in triggers):
            if len(" ".join(selected + [fact])) > max_chars:
                continue
            selected.append(fact)
            if len(selected) == 2:
                break
    return " ".join(selected)
