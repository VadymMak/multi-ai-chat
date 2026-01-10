"""
Debate Manager Service
Управляет процессом дебатов между AI моделями
"""

import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.providers.factory import ask_model
from app.config.debate_prompts import (
    get_round_config,
    PROPOSER_PROMPT,
    CRITIC_PROMPT,
    DEFENDER_PROMPT,
    JUDGE_PROMPT
)


class DebateManager:
    """
    Менеджер для управления дебатами между AI моделями
    """
    
    def __init__(self):
        self.rounds_history: List[Dict[str, Any]] = []
        self.total_tokens = 0
        self.total_cost = 0.0
        
    def start_debate(
        self, 
        topic: str, 
        rounds: int = 3,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Запускает полный цикл дебата
        
        Args:
            topic: Вопрос для дебата
            rounds: Количество раундов (по умолчанию 3)
            session_id: ID сессии (опционально)
            
        Returns:
            Полная структура дебата с результатами
        """
        debate_id = str(uuid.uuid4())
        self.rounds_history = []
        self.total_tokens = 0
        self.total_cost = 0.0
        
        try:
            # Round 1: GPT-4o предлагает решение
            round1_result = self._execute_round(
                round_num=1,
                topic=topic,
                context={}
            )
            
            # Round 2: Claude Sonnet критикует
            round2_result = self._execute_round(
                round_num=2,
                topic=topic,
                context={"previous_solution": round1_result["content"]}
            )
            
            # Round 3: GPT-4o отвечает на критику
            round3_result = self._execute_round(
                round_num=3,
                topic=topic,
                context={
                    "original_solution": round1_result["content"],
                    "critique": round2_result["content"]
                }
            )
            
            # Final: Claude Opus синтезирует финальное решение
            final_solution = self._synthesize_final(
                topic=topic,
                round1=round1_result["content"],
                round2=round2_result["content"],
                round3=round3_result["content"]
            )
            
            return {
                "debate_id": debate_id,
                "topic": topic,
                "session_id": session_id,
                "rounds": self.rounds_history,
                "final_solution": final_solution,
                "total_tokens": self.total_tokens,
                "total_cost": round(self.total_cost, 4),
                "created_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            raise Exception(f"Debate failed: {str(e)}")
    
    def _execute_round(
        self,
        round_num: int,
        topic: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Выполняет один раунд дебата
        
        Args:
            round_num: Номер раунда (1, 2, 3)
            topic: Вопрос для дебата
            context: Контекст из предыдущих раундов
            
        Returns:
            Результат раунда
        """
        config = get_round_config(round_num)
        
        # Формируем промпт для раунда
        prompt = self._format_prompt(
            config["prompt_template"],
            topic=topic,
            **context
        )
        
        # Вызываем модель
        try:
            # ask_model returns a string directly, not a dict
            content = ask_model(
                messages=[{"role": "user", "content": prompt}],
                model_key=config["model_key"],
                system_prompt=None,  # Промпт уже в сообщении
                max_tokens=config["max_tokens"]
            )
            
            # Estimate tokens from content length (rough estimate)
            tokens_used = len(content.split()) * 1.3  # Rough token estimate
            
            # Примерный расчет стоимости (можно улучшить)
            cost = self._estimate_cost(config["model_key"], tokens_used)
            
            round_result = {
                "round_num": round_num,
                "model": config["model_key"],
                "role": config["role"],
                "content": content,
                "tokens": tokens_used,
                "cost": round(cost, 4)
            }
            
            self.rounds_history.append(round_result)
            self.total_tokens += tokens_used
            self.total_cost += cost
            
            return round_result
            
        except Exception as e:
            raise Exception(f"Round {round_num} failed with {config['model_key']}: {str(e)}")
    
    def _synthesize_final(
        self,
        topic: str,
        round1: str,
        round2: str,
        round3: str
    ) -> Dict[str, Any]:
        """
        Создает финальное синтезированное решение через Claude Opus
        
        Args:
            topic: Вопрос для дебата
            round1: Контент первого раунда
            round2: Контент второго раунда
            round3: Контент третьего раунда
            
        Returns:
            Финальное решение
        """
        config = get_round_config("final")
        
        # Формируем финальный промпт
        prompt = JUDGE_PROMPT.format(
            topic=topic,
            round1=round1,
            round2=round2,
            round3=round3
        )
        
        try:
            # ask_model returns a string directly
            content = ask_model(
                messages=[{"role": "user", "content": prompt}],
                model_key=config["model_key"],
                system_prompt=None,
                max_tokens=config["max_tokens"]
            )
            
            # Estimate tokens from content length
            tokens_used = len(content.split()) * 1.3
            cost = self._estimate_cost(config["model_key"], tokens_used)
            
            self.total_tokens += tokens_used
            self.total_cost += cost
            
            return {
                "model": config["model_key"],
                "role": config["role"],
                "content": content,
                "tokens": tokens_used,
                "cost": round(cost, 4)
            }
            
        except Exception as e:
            raise Exception(f"Final synthesis failed: {str(e)}")
    
    def _format_prompt(self, template: str, **kwargs) -> str:
        """
        Форматирует промпт с подстановкой переменных
        
        Args:
            template: Шаблон промпта
            **kwargs: Переменные для подстановки
            
        Returns:
            Отформатированный промпт
        """
        try:
            return template.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"Missing required prompt variable: {e}")
    
    def _estimate_cost(self, model_key: str, tokens: int) -> float:
        """
        Примерный расчет стоимости запроса
        
        Args:
            model_key: Ключ модели
            tokens: Количество токенов
            
        Returns:
            Стоимость в USD
        """
        # Примерные цены (нужно обновить согласно реальным)
        price_per_1k = {
            "gpt-4o": 0.005,  # $5 per 1M tokens
            "claude-3-5-sonnet": 0.003,  # $3 per 1M tokens
            "claude-opus-4": 0.015  # $15 per 1M tokens
        }
        
        rate = price_per_1k.get(model_key, 0.005)
        return (tokens / 1000) * rate


# Singleton instance
debate_manager = DebateManager()
