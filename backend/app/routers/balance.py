"""
API Balance monitoring endpoint
Проверяет доступность OpenAI и Claude API ключей
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import httpx
import os
from datetime import datetime
from pathlib import Path
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# Кеш для хранения результатов (5 минут)
balance_cache = {
    "data": None,
    "timestamp": None,
    "cache_duration": 300  # 5 минут в секундах
}


class BalanceInfo(BaseModel):
    """Информация о балансе провайдера"""
    available: bool
    balance: Optional[str] = None
    usage_this_month: Optional[str] = None
    error: Optional[str] = None
    last_updated: Optional[str] = None


class BalanceResponse(BaseModel):
    """Ответ с информацией о балансах"""
    openai: BalanceInfo
    claude: BalanceInfo
    cached: bool = False


def get_openai_key_from_env() -> tuple[Optional[str], dict[str, any]]:
    """
    Получает OpenAI ключ из environment с детальной диагностикой.
    
    Returns:
        tuple: (api_key, diagnostics_dict)
    """
    diagnostics = {
        "method": "unknown",
        "key_length": 0,
        "key_preview": "N/A",
        "warnings": [],
        "env_file_path": None,
        "env_file_exists": False,
    }
    
    # ============================================================
    # METHOD 1: Direct from os.environ (уже загружен в memory)
    # ============================================================
    key_direct = os.environ.get("OPENAI_API_KEY")
    
    # ⚠️ ВАЖНО: Проверяем что ключ НЕ маскированный!
    if key_direct and len(key_direct) > 50:  # ← Только если длина > 50
        diagnostics["method"] = "os.environ (already loaded)"
        diagnostics["key_length"] = len(key_direct)
        diagnostics["key_preview"] = f"{key_direct[:20]}...{key_direct[-10:]}" if len(key_direct) > 30 else key_direct
        return key_direct, diagnostics
    
    # Если ключ короткий - ignore, попробуем загрузить из файла
    if key_direct and len(key_direct) <= 50:
        diagnostics["warnings"].append(f"os.environ key too short ({len(key_direct)} chars), reloading from file")
    
    # ============================================================
    # METHOD 2: Force reload from .env file
    # ============================================================
    try:
        from dotenv import load_dotenv, dotenv_values
        
        # ✅ ИСПРАВЛЕНО: Правильный путь к .env
        # routers/balance.py -> app/ -> backend/ -> .env
        current_file = Path(__file__)           # balance.py
        app_dir = current_file.parent.parent    # app/
        backend_dir = app_dir.parent            # backend/
        env_path = backend_dir / ".env"         # backend/.env
        
        diagnostics["env_file_path"] = str(env_path)
        diagnostics["env_file_exists"] = env_path.exists()
        
        logger.info(f"🔍 [Diagnostic] Looking for .env at: {env_path}")
        
        if env_path.exists():
            # Load fresh from file
            env_vars = dotenv_values(env_path)
            file_key = env_vars.get("OPENAI_API_KEY")
            
            if file_key:
                diagnostics["method"] = ".env file (fresh load)"
                diagnostics["key_length"] = len(file_key)
                diagnostics["key_preview"] = f"{file_key[:20]}...{file_key[-10:]}" if len(file_key) > 30 else file_key
                
                # Also reload into environment for next time
                load_dotenv(env_path, override=True)
                
                return file_key, diagnostics
            else:
                diagnostics["warnings"].append("OPENAI_API_KEY not found in .env file")
        else:
            diagnostics["warnings"].append(f".env file not found at {env_path}")
            
            # ✅ TRY ALTERNATIVE PATH: Maybe .env is in project root?
            project_root = backend_dir.parent  # ai-assistant/
            alt_env_path = project_root / ".env"
            
            logger.info(f"🔍 [Diagnostic] Trying alternative path: {alt_env_path}")
            
            if alt_env_path.exists():
                env_vars = dotenv_values(alt_env_path)
                file_key = env_vars.get("OPENAI_API_KEY")
                
                if file_key:
                    diagnostics["method"] = ".env file (alternative path)"
                    diagnostics["key_length"] = len(file_key)
                    diagnostics["key_preview"] = f"{file_key[:20]}...{file_key[-10:]}" if len(file_key) > 30 else file_key
                    diagnostics["env_file_path"] = str(alt_env_path)
                    diagnostics["env_file_exists"] = True
                    
                    load_dotenv(alt_env_path, override=True)
                    
                    return file_key, diagnostics
    
    except Exception as e:
        diagnostics["warnings"].append(f"Failed to load .env: {str(e)}")
    
    # ============================================================
    # METHOD 3: Try alternative env variable names (legacy)
    # ============================================================
    alternative_keys = [
        "CHATITNOW_API_KEY",
        "OPEN_API_KEY",
        "OPENAI_KEY"
    ]
    
    for alt_name in alternative_keys:
        alt_key = os.environ.get(alt_name)
        if alt_key and len(alt_key) > 50:  # ← Только если длина > 50
            diagnostics["method"] = f"alternative env var: {alt_name}"
            diagnostics["key_length"] = len(alt_key)
            diagnostics["key_preview"] = f"{alt_key[:20]}...{alt_key[-10:]}" if len(alt_key) > 30 else alt_key
            diagnostics["warnings"].append(f"Using {alt_name} instead of OPENAI_API_KEY (deprecated)")
            return alt_key, diagnostics
    
    # ============================================================
    # NO KEY FOUND
    # ============================================================
    diagnostics["method"] = "none"
    diagnostics["warnings"].append("No OpenAI key found in any location")
    
    return None, diagnostics


async def get_openai_balance() -> BalanceInfo:
    """
    Проверяет доступность OpenAI API ключа с полной диагностикой
    
    Note: OpenAI не предоставляет публичный API для проверки баланса
    для обычных API ключей. Billing endpoints требуют session key.
    Поэтому мы просто проверяем доступность через /v1/models
    """
    
    # ============================================================
    # STEP 1: Get API key with diagnostics
    # ============================================================
    api_key, diagnostics = get_openai_key_from_env()
    
    # Log diagnostics
    logger.info("=" * 80)
    logger.info("🔍 [OpenAI Balance Check] Diagnostics:")
    logger.info(f"  📌 Method: {diagnostics['method']}")
    logger.info(f"  📏 Key length: {diagnostics['key_length']}")
    logger.info(f"  🔑 Key preview: {diagnostics['key_preview']}")
    logger.info(f"  📄 .env file: {diagnostics['env_file_path']} (exists: {diagnostics['env_file_exists']})")
    
    if diagnostics['warnings']:
        logger.warning("  ⚠️ Warnings:")
        for warning in diagnostics['warnings']:
            logger.warning(f"    - {warning}")
    
    logger.info("=" * 80)
    
    # ============================================================
    # STEP 2: Validate key
    # ============================================================
    if not api_key:
        return BalanceInfo(
            available=False,
            balance=None,
            usage_this_month=None,
            error="OPENAI_API_KEY не установлен в .env",
            last_updated=None
        )
    
    # Validate key format
    if not api_key.startswith("sk-"):
        logger.error(f"❌ Invalid key format: must start with 'sk-', got: {api_key[:10]}...")
        return BalanceInfo(
            available=False,
            balance=None,
            usage_this_month=None,
            error=f"Invalid key format (must start with 'sk-')",
            last_updated=None
        )
    
    # Validate key length (modern keys are ~160+ chars)
    if len(api_key) < 50:
        logger.error(f"❌ Key too short: {len(api_key)} chars (expected 160+)")
        return BalanceInfo(
            available=False,
            balance=None,
            usage_this_month=None,
            error=f"Invalid key length: {len(api_key)} chars (expected 160+). Key may be truncated.",
            last_updated=None
        )
    
    # ============================================================
    # STEP 3: Test API key
    # ============================================================
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        logger.info("🔍 [OpenAI] Calling /v1/models endpoint...")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers=headers
            )
            
            logger.info(f"📡 [OpenAI] Response: {response.status_code}")
            
            if response.status_code == 200:
                logger.info("✅ [OpenAI] Key is valid!")
                return BalanceInfo(
                    available=True,
                    balance="✅ Доступен",
                    usage_this_month="Неизвестно",
                    error=None,
                    last_updated=datetime.now().isoformat()
                )
            
            elif response.status_code == 401:
                # Parse error details
                try:
                    error_data = response.json()
                    error_message = error_data.get("error", {}).get("message", "Неверный API ключ")
                except Exception:
                    error_message = "Неверный API ключ"
                
                logger.error(f"❌ [OpenAI] 401 Unauthorized: {error_message}")
                logger.error(f"   Key used: {api_key[:20]}...{api_key[-10:]}")
                
                return BalanceInfo(
                    available=False,
                    balance=None,
                    usage_this_month=None,
                    error=f"401 Unauthorized: {error_message}",
                    last_updated=None
                )
            
            elif response.status_code == 429:
                return BalanceInfo(
                    available=False,
                    balance=None,
                    usage_this_month=None,
                    error="Rate limit exceeded. Please try again later.",
                    last_updated=None
                )
            
            else:
                # Other error
                try:
                    error_data = response.json()
                    error_message = error_data.get("error", {}).get("message", f"HTTP {response.status_code}")
                except Exception:
                    error_message = f"HTTP {response.status_code}"
                
                logger.error(f"❌ [OpenAI] Error: {error_message}")
                
                return BalanceInfo(
                    available=False,
                    balance=None,
                    usage_this_month=None,
                    error=f"API Error: {error_message}",
                    last_updated=None
                )
                
    except httpx.TimeoutException:
        logger.error("❌ [OpenAI] Timeout connecting to API")
        return BalanceInfo(
            available=False,
            balance=None,
            usage_this_month=None,
            error="Timeout при подключении к OpenAI (>10 seconds)",
            last_updated=None
        )
    
    except httpx.ConnectError as e:
        logger.error(f"❌ [OpenAI] Connection error: {e}")
        return BalanceInfo(
            available=False,
            balance=None,
            usage_this_month=None,
            error="Не удалось подключиться к OpenAI. Проверьте интернет.",
            last_updated=None
        )
    
    except Exception as e:
        logger.error(f"❌ [OpenAI] Unexpected error: {e}")
        return BalanceInfo(
            available=False,
            balance=None,
            usage_this_month=None,
            error=f"Unexpected error: {str(e)[:100]}",
            last_updated=None
        )


async def get_claude_balance() -> BalanceInfo:
    """
    Проверяет доступность Claude (Anthropic) API ключа
    
    Note: Anthropic использует prepaid billing и требует Admin API key
    для получения usage/cost информации. Обычные API ключи могут только
    проверить доступность через тестовый запрос.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    
    if not api_key:
        return BalanceInfo(
            available=False,
            balance=None,
            usage_this_month=None,
            error="ANTHROPIC_API_KEY не установлен",
            last_updated=None
        )
    
    # Validate key format
    if not api_key.startswith("sk-ant-"):
        logger.error(f"❌ Invalid Claude key format: must start with 'sk-ant-'")
        return BalanceInfo(
            available=False,
            balance=None,
            usage_this_month=None,
            error="Invalid key format (must start with 'sk-ant-')",
            last_updated=None
        )
    
    try:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        # Минимальный тестовый запрос для проверки ключа
        test_request = {
            "model": "claude-3-haiku-20240307",  # самая дешевая модель
            "max_tokens": 1,
            "messages": [
                {"role": "user", "content": "test"}
            ]
        }
        
        logger.info("🔍 [Claude] Testing API key...")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=test_request
            )
            
            logger.info(f"📡 [Claude] Response: {response.status_code}")
            
            if response.status_code == 200:
                logger.info("✅ [Claude] Key is valid!")
                return BalanceInfo(
                    available=True,
                    balance="✅ Доступен",
                    usage_this_month="Неизвестно",
                    error=None,
                    last_updated=datetime.now().isoformat()
                )
            
            elif response.status_code == 401:
                return BalanceInfo(
                    available=False,
                    balance=None,
                    usage_this_month=None,
                    error="Неверный API ключ",
                    last_updated=None
                )
            
            elif response.status_code == 529:
                # Service overloaded
                logger.warning("⚠️ [Claude] Service temporarily overloaded (529)")
                return BalanceInfo(
                    available=True,  # Key is valid, service just busy
                    balance="⚠️ Service overloaded",
                    usage_this_month=None,
                    error="Anthropic servers temporarily overloaded. Try again in a moment.",
                    last_updated=datetime.now().isoformat()
                )
            
            elif response.status_code == 400:
                # Может быть "insufficient_balance" error
                try:
                    data = response.json()
                    error_type = data.get("error", {}).get("type", "")
                    if "balance" in error_type.lower():
                        return BalanceInfo(
                            available=False,
                            balance="$0.00",
                            usage_this_month=None,
                            error="Недостаточно credits. Пополните баланс в Console",
                            last_updated=datetime.now().isoformat()
                        )
                    return BalanceInfo(
                        available=False,
                        balance=None,
                        usage_this_month=None,
                        error=f"API Error: {data.get('error', {}).get('message', 'Unknown')}",
                        last_updated=None
                    )
                except Exception:
                    return BalanceInfo(
                        available=False,
                        balance=None,
                        usage_this_month=None,
                        error=f"API Error: HTTP 400",
                        last_updated=None
                    )
            
            else:
                return BalanceInfo(
                    available=False,
                    balance=None,
                    usage_this_month=None,
                    error=f"API Error: HTTP {response.status_code}",
                    last_updated=None
                )
                
    except httpx.TimeoutException:
        logger.error("❌ [Claude] Timeout")
        return BalanceInfo(
            available=False,
            balance=None,
            usage_this_month=None,
            error="Timeout при подключении к Anthropic",
            last_updated=None
        )
    
    except Exception as e:
        logger.error(f"❌ [Claude] Error: {e}")
        return BalanceInfo(
            available=False,
            balance=None,
            usage_this_month=None,
            error=str(e)[:100],
            last_updated=None
        )


def is_cache_valid() -> bool:
    """Проверяет валидность кеша"""
    if balance_cache["data"] is None or balance_cache["timestamp"] is None:
        return False
    
    time_diff = datetime.now() - balance_cache["timestamp"]
    return time_diff.total_seconds() < balance_cache["cache_duration"]


@router.get("/balance", response_model=BalanceResponse)
async def get_api_balance(force_refresh: bool = False):
    """
    Проверить доступность API ключей OpenAI и Claude
    
    Args:
        force_refresh: Принудительно обновить кеш (игнорировать 5-минутный кеш)
    
    Returns:
        BalanceResponse с информацией о доступности ключей
    """
    
    # Проверяем кеш
    if not force_refresh and is_cache_valid():
        cached_data = balance_cache["data"]
        logger.info("📦 [Balance] Returning cached data")
        return BalanceResponse(
            openai=cached_data["openai"],
            claude=cached_data["claude"],
            cached=True
        )
    
    logger.info("🔄 [Balance] Fetching fresh data...")
    
    # Получаем свежие данные
    openai_info = await get_openai_balance()
    claude_info = await get_claude_balance()
    
    response_data = {
        "openai": openai_info,
        "claude": claude_info,
        "cached": False
    }
    
    # Обновляем кеш только если хотя бы один ключ валиден
    if openai_info.available or claude_info.available:
        balance_cache["data"] = response_data
        balance_cache["timestamp"] = datetime.now()
        logger.info("✅ [Balance] Cache updated")
    else:
        logger.warning("⚠️ [Balance] Both keys invalid, not caching")
    
    return BalanceResponse(**response_data)


@router.post("/balance/clear-cache")
async def clear_balance_cache():
    """Очистить кеш баланса (force fresh check next time)"""
    balance_cache["data"] = None
    balance_cache["timestamp"] = None
    logger.info("🗑️ [Balance] Cache cleared")
    
    return {
        "success": True,
        "message": "Кеш очищен. Следующий запрос получит свежие данные."
    }
