from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.core.models import MatchVerdict, Offer, SkillMatch
from src.notify.telegram_notifier import (
    TelegramNotifier,
    TelegramNotifierError,
    TelegramRateLimitError,
    _build_message,
    _fmt_list,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_offer(
    empresa: str | None = 'TechCo',
    ubicacion: str | None = 'Bogotá',
    skills_encontrados: list[str] | None = None,
    skills_faltantes: list[str] | None = None,
    veredicto: MatchVerdict | None = None,
) -> Offer:
    skill_match = SkillMatch(
        skills_encontrados=skills_encontrados or ['Python', 'Docker'],
        skills_faltantes=skills_faltantes or ['Java'],
        fraccion=0.7,
        pasa=True,
    )
    v = veredicto or MatchVerdict(
        score=0.85,
        apto=True,
        razon='Buen perfil',
        puntos_favor=['Python senior', 'API REST'],
        puntos_contra=['Falta Java'],
    )
    return Offer(
        id='abc123def456789',
        fuente='elempleo',
        url='https://example.com/job/1',
        titulo='Backend Dev',
        empresa=empresa,
        ubicacion=ubicacion,
        posted_date=date(2024, 6, 1),
        descripcion_md='## Req\n\nPython.',
        skill_match=skill_match,
        veredicto=v,
    )


def _make_ok_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    return resp


def _make_error_response(status: int, body: str = 'error') -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    return resp


def _make_rate_limit_response(retry_after: int = 3) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {'Retry-After': str(retry_after)}
    return resp


# ---------------------------------------------------------------------------
# _fmt_list
# ---------------------------------------------------------------------------

def test_fmt_list_with_items():
    assert _fmt_list(['A', 'B']) == 'A, B'


def test_fmt_list_empty():
    assert _fmt_list([]) == '—'


# ---------------------------------------------------------------------------
# _build_message
# ---------------------------------------------------------------------------

def test_message_contains_all_fields():
    offer = _make_offer()
    msg = _build_message(offer)

    assert 'Backend Dev' in msg
    assert 'TechCo' in msg
    assert 'Bogotá' in msg
    assert 'https://example.com/job/1' in msg
    assert 'Python' in msg
    assert 'Java' in msg
    assert '85%' in msg
    assert 'Buen perfil' in msg
    assert 'abc123def456' in msg  # short_id = id[:12]
    # Bug M: etiqueta correcta para el gap de skills
    assert 'Skills oferta no en tu perfil' in msg


def test_message_empresa_none_shows_fallback():
    offer = _make_offer(empresa=None)
    msg = _build_message(offer)
    assert 'No especificada' in msg


def test_message_ubicacion_none_shows_fallback():
    offer = _make_offer(ubicacion=None)
    msg = _build_message(offer)
    assert 'No especificada' in msg


def test_message_empty_skills_shows_dash():
    offer = _make_offer(skills_encontrados=[], skills_faltantes=[])
    msg = _build_message(offer)
    assert '—' in msg


def test_message_short_id_is_12_chars():
    offer = _make_offer()
    msg = _build_message(offer)
    assert offer.id[:12] in msg
    assert offer.id[12:] not in msg


# ---------------------------------------------------------------------------
# TelegramNotifier.notify()
# ---------------------------------------------------------------------------

def test_notify_calls_telegram_api():
    notifier = TelegramNotifier(token='tok', chat_id='123')
    offer = _make_offer()

    with patch('httpx.post', return_value=_make_ok_response()) as mock_post:
        notifier.notify(offer)

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert 'bot123' not in str(call_kwargs)  # token correcto incluido en URL
    assert 'tok' in str(call_kwargs)


def test_notify_without_veredicto_raises():
    notifier = TelegramNotifier(token='tok', chat_id='123')
    offer = _make_offer()
    offer.veredicto = None

    with pytest.raises(TelegramNotifierError, match='veredicto'):
        notifier.notify(offer)


def test_notify_raises_on_http_error():
    notifier = TelegramNotifier(token='tok', chat_id='123')
    offer = _make_offer()

    with patch('httpx.post', return_value=_make_error_response(400)):
        with pytest.raises(TelegramNotifierError, match='400'):
            notifier.notify(offer)


def test_notify_raises_on_network_error():
    import httpx as _httpx
    notifier = TelegramNotifier(token='tok', chat_id='123')
    offer = _make_offer()

    with patch('httpx.post', side_effect=_httpx.ConnectError('timeout')):
        with pytest.raises(TelegramNotifierError, match='red'):
            notifier.notify(offer)


def test_notify_retries_on_rate_limit_then_succeeds():
    notifier = TelegramNotifier(token='tok', chat_id='123', retry_on_rate_limit=True)
    offer = _make_offer()

    rate_resp = _make_rate_limit_response(retry_after=0)
    ok_resp = _make_ok_response()

    with patch('httpx.post', side_effect=[rate_resp, ok_resp]):
        with patch('time.sleep') as mock_sleep:
            notifier.notify(offer)
            mock_sleep.assert_called_once_with(0)


def test_notify_raises_rate_limit_if_retry_disabled():
    notifier = TelegramNotifier(token='tok', chat_id='123', retry_on_rate_limit=False)
    offer = _make_offer()

    with patch('httpx.post', return_value=_make_rate_limit_response()):
        with pytest.raises(TelegramRateLimitError):
            notifier.notify(offer)


def test_notify_raises_rate_limit_after_second_429():
    notifier = TelegramNotifier(token='tok', chat_id='123', retry_on_rate_limit=True)
    offer = _make_offer()

    rate_resp = _make_rate_limit_response(retry_after=0)

    with patch('httpx.post', side_effect=[rate_resp, rate_resp]):
        with patch('time.sleep'):
            with pytest.raises(TelegramRateLimitError):
                notifier.notify(offer)


# ---------------------------------------------------------------------------
# Bug M — etiqueta skills_gap
# ---------------------------------------------------------------------------

def test_message_skills_gap_label_is_not_faltantes():
    """Bug M: el template no debe usar '❌ Faltantes:' como etiqueta del gap de skills."""
    offer = _make_offer(skills_faltantes=['Go', 'Rust'])
    msg = _build_message(offer)

    assert '❌ Faltantes:' not in msg
    assert 'Skills oferta no en tu perfil' in msg
    assert 'Go' in msg
    assert 'Rust' in msg


def test_message_skills_gap_empty_shows_dash():
    """Bug M: cuando no hay gap, mostrar '—' igual que antes."""
    offer = _make_offer(skills_faltantes=[])
    msg = _build_message(offer)
    assert '—' in msg


def test_message_skills_gap_field_name_is_skills_gap():
    """Bug M: el campo en el template se llama skills_gap, no skills_faltantes."""
    offer = _make_offer(skills_faltantes=['Kotlin'])
    msg = _build_message(offer)
    # skills_faltantes=['Kotlin'] debe aparecer en el mensaje bajo la etiqueta correcta
    assert 'Kotlin' in msg
    assert 'Skills oferta no en tu perfil' in msg
