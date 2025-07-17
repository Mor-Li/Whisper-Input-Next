import os
import requests
import json
from ..utils.logger import logger

class KimiProcessor:
    def __init__(self):
        self.api_key = os.getenv("KIMI_API_KEY")
        if not self.api_key:
            raise ValueError("未设置 KIMI_API_KEY 环境变量")
        self.base_url = "https://api.moonshot.cn/v1"
        self.model = "kimi-k2-0711-preview"
        
    def polish_text(self, text):
        """使用Kimi API润色文本并添加标点符号"""
        
        system_prompt = "你是一个专业的文本润色助手。请为用户输入的语音识别文本进行润色，主要任务就是给下面句子需要断句的地方，用空格断句断开即可，目的是让人读起来是一句一句的，不需要添加标点符号，下面只输出润色后的文本，不要添加任何解释或说明"        
        url = f"{self.base_url}/chat/completions"
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user", 
                    "content": text
                }
            ],
            "temperature": 0.3,
            "max_tokens": 2000
        }
        
        try:
            logger.info(f"正在使用Kimi API润色文本...")
            response = requests.post(url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            polished_text = result['choices'][0]['message']['content'].strip()
            logger.info(f"Kimi润色完成: {polished_text}")
            return polished_text
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Kimi API请求失败: {e}")
            return text  # 如果API失败，返回原文本
        except KeyError as e:
            logger.error(f"Kimi API响应格式错误: {e}")
            return text
        except Exception as e:
            logger.error(f"Kimi处理过程中出现错误: {e}")
            return text 