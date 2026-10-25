"""Deterministic fallback intent routing for free-form pt-BR messages.

The JEV classifier is the primary router (see ``jev_messages``); this module
keeps the local heuristics used when it is unavailable or abstains. The
composite also keeps cheap fast paths for help, income and strong banking
phrases.
"""

from __future__ import annotations

import re

from myfinance.application.errors import ProviderError
from myfinance.application.intents import MessageIntent, RoutingDecision
from myfinance.application.ports import (
    IntentRouter,
    MessageIntentClassifier,
    SummaryIntentGate,
)
from myfinance.domain.banking import BankingIntent
from myfinance.infrastructure.parsing.amounts import find_amount
from myfinance.infrastructure.parsing.dates import normalize
from myfinance.infrastructure.routing.keywords import KeywordIntentRouter

__all__ = ["DeterministicMessageIntentRouter", "CompositeMessageIntentRouter"]

_INCOME_PATTERNS = (
    r"\bquanto\b.*\b(recebi|recebo|recebe|recebeu|receber|recebido|"
    r"receitas?|ganhei|ganho|ganhou|ganhar|entrou|entraram|entrando|caiu)\b",
    r"\b(?:recebi|recebo|recebeu|ganhei|ganhou)\b",
    r"^\s*(?:entrou|entraram|caiu)\b",
    r"\bsalarios?\b",
)

_DETAIL_PATTERNS = (
    r"\blancamentos?\b",
    r"\blista\s+(?:de\s+|dos\s+|das\s+)?(?:lancamentos?|gastos)\b",
)

_COMPARISON_PATTERNS = (
    r"\b(?:mais|menos)\b.*\b(?:que|do que)\b.*\b(?:mes|semana|ano|periodo)\b",
    r"\bcomparad[oa]s?\b.*\b(?:mes|semana|ano|periodo)\b",
    r"\bem (?:comparacao|relacao)\b.*\b(?:mes|semana|ano|periodo)\b",
    r"\bdo que (?:o |no )?mes (?:passado|anterior)\b",
    r"\b(?:versus|vs)\b.*\b(?:mes|semana|ano|periodo)\b",
)

_HELP_PATTERNS = (
    r"\bo que\s+(?:voce|vc|tu)\s+(?:pode|consegue|sabe)\s+fazer\b",
    r"\bo que\s+(?:voce|vc|tu)\s+faz\b",
    r"\bo que\s+(?:voce|vc|tu)\s+sabe\b",
    r"\bpara que\s+(?:voce|vc|tu)\s+serve\b",
    r"\bcomo\s+(?:voce|vc|tu)\s+funciona\b",
    r"^\s*como\s+funciona\s*[?!.]*$",
    r"\bquais\s+(?:sao\s+)?(?:os\s+|as\s+|suas\s+|seus\s+)?"
    r"(?:comandos|funcoes|funcionalidades|recursos)\b",
    r"\bvoce\s+pode\s+(?:me\s+)?ajudar\b",
    r"^\s*(?:pode|poderia)\s+me\s+ajudar\s*[?!.]*$",
    r"\bcomo\s+(?:eu\s+)?(?:uso|usar)\s+(?:voce|vc|o\s+bot)\b",
    r"\bquem\s+(?:e|es)\s+(?:voce|vc)\b",
    r"^\s*(?:ajuda|help)\s*[?!.]*$",
    r"^\s*me\s+ajuda\s*[?!.]*$",
)

_PLAN_PATTERNS = (
    r"\bplano de gastos?\b",
    r"\bplanejamento\b",
    r"\bonde\s+(?:posso\s+)?(?:cortar|diminuir|reduzir)\b",
    r"\bcomo\s+(?:posso\s+)?economizar\b",
    r"\bme\s+ajuda(?:r)?\s+a\s+economizar\b",
    r"\bdicas?\s+(?:para|de)\s+economizar\b",
    r"\breduzir\s+(?:meus\s+)?gastos\b",
    r"\bcortar\s+(?:meus\s+)?gastos\b",
)

_SUMMARY_PATTERNS = (
    r"\bresumo\b",
    r"\bresume\b",
    r"\bbalanco\b",
    r"\bcomo (estao|esta)\b.*\bgastos?\b",
    r"\bmeus gastos\b",
    r"\bquanto\b.*\b(gastei|gastos?|gaste|gasto)\b",
    r"\bquanto\b.*\b(planejei|tenho)\b",
    r"\bquanto\b.*\b(deu|ficou|custou|custa|foi)\b",
    r"\bgastos (de|do|da|desse|deste|nesse|neste)\b",
)

_TOP_MONTH_PATTERNS = (
    r"\bqual\b.*\bmes\b.*\bmais\b.*\b(gastei|gasto|gastos)\b",
    r"\bqual\b.*\bmes\b.*\b(gastei|gasto|gastos)\b.*\bmais\b",
    r"\bmes\b.*\bmais\b.*\b(gastei|gasto|gastos)\b",
    r"\bmes com mais gastos\b",
    r"\bmaior gasto\b",
)

_SPENDING_QUERY_STOPWORDS = frozenset(
    {
        "quanto",
        "quantos",
        "qual",
        "quais",
        "gastei",
        "gasto",
        "gastos",
        "gaste",
        "paguei",
        "pago",
        "pagos",
        "comprei",
        "em",
        "com",
        "no",
        "na",
        "nos",
        "nas",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "esse",
        "essa",
        "este",
        "esta",
        "nesse",
        "nessa",
        "neste",
        "nesta",
        "mes",
        "semana",
        "ano",
        "anos",
        "hoje",
        "ontem",
        "amanha",
        "passado",
        "passada",
        "atual",
        "ultimo",
        "ultima",
        "dia",
        "dias",
        "por",
        "para",
        "o",
        "a",
        "os",
        "as",
        "e",
        "que",
        "como",
        "estao",
        "quero",
        "comparado",
        "neste",
        "nesse",
        "nesta",
        "nessa",
        "deste",
        "desse",
        "desta",
        "dessa",
        "ao",
        "aos",
        "ou",
        "isso",
        "esse",
        "essa",
        "valor",
        "total",
        "quantia",
        "comparada",
        "comparacao",
        "relacao",
        "versus",
        "vs",
        "mais",
        "menos",
        "anterior",
        "retrasado",
        "retrasada",
        "recebi",
        "recebo",
        "recebe",
        "recebeu",
        "receber",
        "recebido",
        "receita",
        "receitas",
        "ganhei",
        "ganho",
        "ganhou",
        "ganhar",
        "salario",
        "salarios",
        "entrou",
        "entraram",
        "entrando",
        "caiu",
        "resumo",
        "resume",
        "balanco",
        "ver",
        "mostra",
        "mostrar",
        "mostre",
        "lista",
        "listar",
        "exibe",
        "exibir",
        "me",
        "te",
        "lhe",
        "categoria",
        "categorias",
        "foi",
        "foram",
        "meu",
        "minha",
        "meus",
        "minhas",
        "eu",
        "tu",
        "voce",
        "voces",
        "ele",
        "ela",
        "eles",
        "elas",
        "gente",
        "deu",
        "deram",
        "ficou",
        "ficaram",
        "custou",
        "custaram",
        "custa",
        "custam",
        "valeu",
        "valeram",
        "saiu",
        "sairam",
        "entrou",
        "entraram",
        "sera",
        "serao",
        "vai",
        "vao",
        "vou",
        "vamos",
        "tenho",
        "tem",
        "temos",
        "tinha",
        "tinham",
        "era",
        "eram",
        "sou",
        "somos",
        "sao",
        "gastou",
        "gastaram",
        "pagou",
        "pagaram",
        "comprou",
        "compraram",
        "banco",
        "bancos",
        "conta",
        "contas",
        "cartao",
        "cartoes",
        "compras",
        "compra",
        "comprar",
        "saldo",
        "saldos",
        "extrato",
        "extratos",
        "transacao",
        "transacoes",
        "pagamento",
        "pagamentos",
        "fatura",
        "faturas",
        "pix",
        "limite",
        "credito",
        "debito",
    }
)

_MONTH_NAMES = frozenset(
    {
        "janeiro",
        "fevereiro",
        "marco",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    }
)

_TOKEN_PUNCTUATION = ".,!?;:\"'()[]{}…"

_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DATE_SPAN_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def _asks_for_income(text: str) -> bool:
    normalized = normalize(text)
    return any(re.search(pattern, normalized) for pattern in _INCOME_PATTERNS)


def _asks_for_spending_comparison(text: str) -> bool:
    normalized = normalize(text)
    return any(
        re.search(pattern, normalized) for pattern in _COMPARISON_PATTERNS
    )


def _asks_for_period_details(text: str) -> bool:
    normalized = normalize(text)
    return any(re.search(pattern, normalized) for pattern in _DETAIL_PATTERNS)


def _asks_for_help(text: str) -> bool:
    normalized = normalize(text)
    return any(re.search(pattern, normalized) for pattern in _HELP_PATTERNS)


def _asks_for_summary(text: str) -> bool:
    normalized = normalize(text)
    return any(re.search(pattern, normalized) for pattern in _SUMMARY_PATTERNS)


def _asks_for_top_month(text: str) -> bool:
    normalized = normalize(text)
    return any(re.search(pattern, normalized) for pattern in _TOP_MONTH_PATTERNS)


def _asks_for_spending_plan(text: str) -> bool:
    normalized = normalize(text)
    return any(re.search(pattern, normalized) for pattern in _PLAN_PATTERNS)


def _has_explicit_amount(text: str) -> bool:
    """Return whether ``text`` carries a money-like amount outside dates.

    Dates and four-digit years are masked first, so an explicit year or
    ``DD/MM`` reference never reads as a monetary value.
    """
    masked = _ISO_DATE_RE.sub(" ", text)
    masked = _DATE_SPAN_RE.sub(" ", masked)
    masked = _YEAR_RE.sub(" ", masked)
    return find_amount(masked) is not None


def _looks_like_spending_query(text: str) -> bool:
    """Return whether ``text`` asks a spending question with a concrete subject.

    Period-only questions ("quanto gastei hoje?") stay summaries, and
    registration messages without a spending trigger never reach the search.
    """
    normalized = normalize(text)
    if _asks_for_top_month(text) or _asks_for_spending_plan(text):
        return False
    if not re.search(r"\b(?:quanto|gastei|gastou|gastos?)\b", normalized):
        return False
    has_subject = False
    for raw in normalized.split():
        token = raw.strip(_TOKEN_PUNCTUATION)
        if not token:
            continue
        if token in _SPENDING_QUERY_STOPWORDS:
            continue
        if token in _MONTH_NAMES:
            continue
        if any(character.isdigit() for character in token):
            continue
        has_subject = True
        break
    if not has_subject:
        return False
    return not _has_explicit_amount(text)


class DeterministicMessageIntentRouter:
    """Classifies the finance part of a message with pt-BR heuristics only."""

    def __init__(self, summary_gate: SummaryIntentGate | None = None) -> None:
        self._summary_gate = summary_gate

    async def route(self, text: str) -> RoutingDecision:
        if _asks_for_help(text):
            return RoutingDecision(MessageIntent.HELP)
        if _asks_for_income(text):
            return RoutingDecision(MessageIntent.INCOME)
        if _asks_for_period_details(text):
            return RoutingDecision(MessageIntent.PERIOD_DETAILS)
        if _asks_for_spending_comparison(text):
            return RoutingDecision(MessageIntent.SPENDING_COMPARISON)
        if _looks_like_spending_query(text):
            return RoutingDecision(MessageIntent.SPENDING_SEARCH)
        if _asks_for_spending_plan(text):
            return RoutingDecision(MessageIntent.SPENDING_PLAN)
        if _asks_for_top_month(text):
            return RoutingDecision(MessageIntent.TOP_MONTH)

        decision = None
        if self._summary_gate is not None:
            try:
                decision = await self._summary_gate.should_summarize(text)
            except ProviderError:
                decision = None
        wants_summary = (
            decision if decision is not None else _asks_for_summary(text)
        )
        if wants_summary:
            return RoutingDecision(MessageIntent.SUMMARY)

        return RoutingDecision(MessageIntent.REGISTER)


class CompositeMessageIntentRouter:
    """Prefers JEV, keeping cheap deterministic fast paths and a fallback."""

    def __init__(
        self,
        keywords: KeywordIntentRouter | None = None,
        jev: IntentRouter | None = None,
        summary_gate: SummaryIntentGate | None = None,
        classifier: MessageIntentClassifier | None = None,
    ) -> None:
        self._keywords = keywords or KeywordIntentRouter()
        self._jev = jev
        self._finance = DeterministicMessageIntentRouter(summary_gate)
        self._classifier = classifier

    async def route(self, text: str) -> RoutingDecision:
        banking = await self._keywords.route(text)
        if banking is not None and banking is not BankingIntent.NONE:
            return RoutingDecision(MessageIntent.BANKING, banking)

        # These two are cheap and must work even when the classifier is
        # unavailable; everything else prefers the JEV classifier.
        if _asks_for_help(text):
            return RoutingDecision(MessageIntent.HELP)
        if _asks_for_income(text):
            return RoutingDecision(MessageIntent.INCOME)

        if self._classifier is not None:
            decision = await self._classifier.classify(text)
            if decision is not None:
                return decision

        decision = await self._finance.route(text)
        if decision.intent is not MessageIntent.REGISTER:
            return decision

        # Ambiguous banking hints are checked last, so a clear spending
        # question that merely mentions "cartão" or "conta" is not stolen by
        # the banking path.
        if banking is None and self._jev is not None:
            banking_intent = await self._jev.route(text)
            if banking_intent is not BankingIntent.NONE:
                return RoutingDecision(MessageIntent.BANKING, banking_intent)

        return decision
