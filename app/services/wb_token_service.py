# app/services/wb_token_service.py
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class WBTokenDecoder:
    """Сервис для работы с токенами Wildberries"""
    
    def decode_wb_token(token: str) -> Optional[Dict[str, Any]]:
        """
        Декодирует JWT токен Wildberries без проверки подписи
        
        Args:
            token: JWT токен Wildberries
            
        Returns:
            Словарь с декодированными данными или None в случае ошибки
        """
        try:
            # Декодируем без проверки подписи (нам нужны только данные)
            decoded = jwt.decode(
                token,
                options={"verify_signature": False},
                algorithms=["HS256"]  # Wildberries использует HS256
            )
            return decoded
        except jwt.exceptions.DecodeError as e:
            logger.error(f"Ошибка декодирования токена: {e}")
            return None
        except Exception as e:
            logger.error(f"Неизвестная ошибка при декодировании токена: {e}")
            return None
    
    def get_token_expiry(decoded_token: Dict[str, Any]) -> Optional[datetime]:
        """
        Извлекает дату истечения токена
        
        Args:
            decoded_token: Декодированный токен
            
        Returns:
            datetime объект с датой истечения или None
        """
        if 'exp' in decoded_token:
            # exp - Unix timestamp в секундах
            return datetime.fromtimestamp(decoded_token['exp'])
        return None
    
    
    def get_token_info(token: str) -> Optional[Dict[str, Any]]:
        """
        Получает полную информацию о токене
        
        Returns:
            Словарь с информацией о токене или None
        """
        decoded = WBTokenDecoder.decode_wb_token(token)
        if not decoded:
            return None
        
        expiry_date = WBTokenDecoder.get_token_expiry(decoded)
        
        # Определяем тип токена
        token_type = "Неизвестный"
        if 'acc' in decoded:
            acc = decoded['acc']
            if acc == 1:
                token_type = "Базовый токен"
            elif acc == 2:
                token_type = "Тестовый токен"
            elif acc == 3:
                token_type = "Персональный токен"
            elif acc == 4:
                token_type = "Сервисный токен"
        
        # Парсим права доступа из битовой маски
        permissions = []
        if 's' in decoded:
            s = decoded['s']
            # Проверяем каждый бит согласно документации
            if s & (1 << 1):  # Бит 1
                permissions.append("Контент")
            if s & (1 << 2):  # Бит 2
                permissions.append("Аналитика")
            if s & (1 << 3):  # Бит 3
                permissions.append("Цены и скидки")
            if s & (1 << 4):  # Бит 4
                permissions.append("Маркетплейс")
            if s & (1 << 5):  # Бит 5
                permissions.append("Статистика")
            if s & (1 << 6):  # Бит 6
                permissions.append("Продвижение")
            if s & (1 << 7):  # Бит 7
                permissions.append("Вопросы и отзывы")
            if s & (1 << 9):  # Бит 9
                permissions.append("Чат с покупателями")
            if s & (1 << 10):  # Бит 10
                permissions.append("Поставки")
            if s & (1 << 11):  # Бит 11
                permissions.append("Возвраты покупателями")
            if s & (1 << 12):  # Бит 12
                permissions.append("Документы")
            if s & (1 << 13):  # Бит 13
                permissions.append("Финансы")
            if s & (1 << 16):  # Бит 16
                permissions.append("Пользователи")
            if s & (1 << 30):  # Бит 30
                permissions.append("Только чтение")
        
        return {
            'id': decoded.get('id'),
            'seller_id': decoded.get('sid'),
            'expiry_date': expiry_date,
            'token_type': token_type,
            'permissions': permissions,
            'is_test': decoded.get('t', False),
            'decoded': decoded  # Полные декодированные данные
        }
    
    
    def is_token_expired(token: str) -> bool:
        """
        Проверяет, истек ли срок действия токена
        
        Returns:
            True если токен истек, False если действителен
        """
        decoded = WBTokenDecoder.decode_wb_token(token)
        if not decoded or 'exp' not in decoded:
            return True
        
        current_time = datetime.now().timestamp()
        return decoded['exp'] < current_time
    
    
    def get_days_to_expiry(token: str) -> Optional[int]:
        """
        Получает количество дней до истечения токена
        
        Returns:
            Количество дней или None если токен невалиден
        """
        decoded = WBTokenDecoder.decode_wb_token(token)
        if not decoded or 'exp' not in decoded:
            return None
        
        expiry_time = decoded['exp']
        current_time = datetime.now().timestamp()
        
        seconds_left = expiry_time - current_time
        if seconds_left <= 0:
            return 0
        
        days_left = int(seconds_left / (24 * 60 * 60))
        return days_left