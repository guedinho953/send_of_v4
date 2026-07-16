"""
Integração com Qwen 2.5 via llama.cpp para:
1. Verificar consistência entre comando judicial e cumprimento
2. Gerar documentos (ofícios, mandados) com dados do processo
3. Sugerir planos de cumprimento baseados em RAG

Requisitos:
- llama.cpp rodando com: ./llama-server -m qwen2.5-3b-q4_k_m.gguf --port 8080
- Ou usar binding Python: pip install llama-cpp-python
"""

import requests
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import re


class LlamaBackend(Enum):
    """Backend do llama.cpp"""
    SERVER = "server"  # llama-server (HTTP API)
    PYTHON = "python"  # llama-cpp-python (binding direto)


@dataclass
class LlamaConfig:
    """Configuração do llama.cpp"""
    backend: LlamaBackend = LlamaBackend.SERVER
    server_url: str = "http://localhost:8080"
    model_path: str = ""  # Para backend PYTHON
    n_ctx: int = 4096
    n_gpu_layers: int = -1  # -1 = todos
    temperature: float = 0.3
    max_tokens: int = 1024
    top_p: float = 0.9


class QwenDocumentGenerator:
    """Gera documentos usando Qwen 2.5"""
    
    def __init__(self, config: LlamaConfig):
        self.config = config
        self._client = None
    
    @property
    def client(self):
        """Lazy loading do cliente"""
        if self._client is None:
            if self.config.backend == LlamaBackend.PYTHON:
                from llama_cpp import Llama
                self._client = Llama(
                    model_path=self.config.model_path,
                    n_ctx=self.config.n_ctx,
                    n_gpu_layers=self.config.n_gpu_layers,
                    verbose=False
                )
        return self._client
    
    def gerar_oficio(
        self,
        dados_processo: Dict,
        tipo_oficio: str = "intimacao",
        contexto_rag: Optional[Dict] = None
    ) -> str:
        """
        Gera ofício com dados do processo
        
        Args:
            dados_processo: Dados do processo (partes, comandos, etc)
            tipo_oficio: Tipo de ofício (intimacao, citacao, penhora, etc)
            contexto_rag: Contexto do RAG (cumprimentos similares)
        
        Returns:
            Texto do ofício gerado
        """
        prompt = self._construir_prompt_oficio(dados_processo, tipo_oficio, contexto_rag)
        
        if self.config.backend == LlamaBackend.SERVER:
            return self._gerar_via_server(prompt)
        else:
            return self._gerar_via_python(prompt)
    
    def verificar_consistencia(
        self,
        comando_judicial: str,
        cumprimento_realizado: str,
        contexto_processo: Optional[Dict] = None
    ) -> Dict:
        """
        Verifica se o cumprimento está consistente com o comando judicial
        
        Args:
            comando_judicial: Texto do comando judicial
            cumprimento_realizado: Descrição do que foi feito
            contexto_processo: Contexto adicional do processo
        
        Returns:
            Dict com:
            - consistente: bool
            - justificativa: str
            - observacoes: List[str]
            - sugestoes: List[str]
        """
        prompt = self._construir_prompt_verificacao(
            comando_judicial,
            cumprimento_realizado,
            contexto_processo
        )
        
        resposta = self._gerar_resposta(prompt)
        
        return self._parse_verificacao(resposta)
    
    def sugerir_plano_cumprimento(
        self,
        comando_judicial: str,
        dados_processo: Dict,
        cumprimentos_similares: List[Dict]
    ) -> Dict:
        """
        Sugere plano de cumprimento baseado em RAG
        
        Args:
            comando_judicial: Texto do comando
            dados_processo: Dados do processo
            cumprimentos_similares: Lista de cumprimentos similares (do RAG)
        
        Returns:
            Dict com plano sugerido
        """
        prompt = self._construir_prompt_plano(
            comando_judicial,
            dados_processo,
            cumprimentos_similares
        )
        
        resposta = self._gerar_resposta(prompt)
        
        return self._parse_plano(resposta)
    
    def _construir_prompt_oficio(
        self,
        dados_processo: Dict,
        tipo_oficio: str,
        contexto_rag: Optional[Dict]
    ) -> str:
        """Constrói prompt para geração de ofício"""
        
        partes = dados_processo.get('partes', [])
        comando = dados_processo.get('comando_judicial', '')
        processo_numero = dados_processo.get('numero', '')
        
        # Formata partes
        partes_texto = "\n".join([
            f"- {p.get('nome', 'N/A')} ({p.get('papel', 'N/A')})"
            for p in partes[:5]
        ])
        
        # Contexto RAG
        rag_texto = ""
        if contexto_rag:
            similares = contexto_rag.get('cumprimentos_similares', [])
            if similares:
                rag_texto = "\n\nExemplos de cumprimentos similares já realizados:\n"
                for i, ex in enumerate(similares[:3], 1):
                    rag_texto += f"{i}. {ex.get('descricao', 'N/A')}\n"
        
        prompt = f"""Você é um assistente jurídico especializado em cartórios de vara de juizados especiais.

Gere um ofício judicial formal e preciso baseado nos dados abaixo.

DADOS DO PROCESSO:
Número: {processo_numero}
Partes:
{partes_texto}

COMANDO JUDICIAL:
{comando}

TIPO DE OFÍCIO: {tipo_oficio}
{rag_texto}

INSTRUÇÕES:
1. Use linguagem formal e jurídica adequada
2. Inclua todos os dados necessários para o cumprimento
3. Seja claro e objetivo
4. Siga o formato padrão de ofícios judiciais da 2ª VSJ de Paulo Afonso - BA
5. Inclua: cabeçalho, destinatário, referência ao processo, comando a cumprir, prazo (se houver), local e data

OFÍCIO:"""
        
        return prompt
    
    def _construir_prompt_verificacao(
        self,
        comando_judicial: str,
        cumprimento_realizado: str,
        contexto_processo: Optional[Dict]
    ) -> str:
        """Constrói prompt para verificação de consistência"""
        
        contexto_texto = ""
        if contexto_processo:
            contexto_texto = f"""
CONTEXTO ADICIONAL:
- Processo: {contexto_processo.get('numero', 'N/A')}
- Tipo: {contexto_processo.get('classe', 'N/A')}
- Partes: {', '.join([p.get('nome', '') for p in contexto_processo.get('partes', [])[:3]])}
"""
        
        prompt = f"""Você é um assistente jurídico especializado em verificar cumprimentos de decisões judiciais.

Analise se o cumprimento realizado está CONSISTENTE com o comando judicial.

COMANDO JUDICIAL:
{comando_judicial}

CUMPRIMENTO REALIZADO:
{cumprimento_realizado}
{contexto_texto}

RESPONDA EM JSON EXATAMENTE NESTE FORMATO:
{{
    "consistente": true/false,
    "justificativa": "explicação breve",
    "observacoes": ["lista de observações"],
    "sugestoes": ["sugestões de melhoria se houver"]
}}

ANÁLISE:"""
        
        return prompt
    
    def _construir_prompt_plano(
        self,
        comando_judicial: str,
        dados_processo: Dict,
        cumprimentos_similares: List[Dict]
    ) -> str:
        """Constrói prompt para sugestão de plano"""
        
        # Formata cumprimentos similares
        similares_texto = ""
        if cumprimentos_similares:
            similares_texto = "\nCUMPRIMENTOS SIMILARES JÁ REALIZADOS:\n"
            for i, c in enumerate(cumprimentos_similares[:5], 1):
                similares_texto += f"\n{i}. Tipo: {c.get('tipo_acao', 'N/A')}\n"
                similares_texto += f"   Descrição: {c.get('descricao', 'N/A')}\n"
                similares_texto += f"   Passos: {', '.join(c.get('passos', []))}\n"
                similares_texto += f"   Status: {c.get('status', 'N/A')}\n"
        
        partes = dados_processo.get('partes', [])
        partes_texto = ", ".join([p.get('nome', '') for p in partes[:3]])
        
        prompt = f"""Você é um assistente jurídico especializado em planejar cumprimentos de decisões judiciais.

Com base no comando judicial e em exemplos de cumprimentos similares já realizados, sugira um PLANO DE CUMPRIMENTO.

COMANDO JUDICIAL:
{comando_judicial}

DADOS DO PROCESSO:
- Número: {dados_processo.get('numero', 'N/A')}
- Partes: {partes_texto}
{similares_texto}

RESPONDA EM JSON EXATAMENTE NESTE FORMATO:
{{
    "plano_sugerido": {{
        "tipo_acao": "tipo principal (email_enviado, juntada_projudi, oficio_gerado, etc)",
        "descricao": "descrição do que deve ser feito",
        "passos": ["passo 1", "passo 2", "passo 3"],
        "destinatarios": ["lista de destinatários"],
        "prazo": "prazo sugerido",
        "observacoes": "observações importantes"
    }},
    "alternativas": [
        {{
            "tipo_acao": "tipo alternativo",
            "descricao": "descrição alternativa"
        }}
    ],
    "confianca": 0.85,
    "justificativa": "por que este plano é adequado"
}}

PLANO:"""
        
        return prompt
    
    def _gerar_resposta(self, prompt: str) -> str:
        """Gera resposta usando o backend configurado"""
        if self.config.backend == LlamaBackend.SERVER:
            return self._gerar_via_server(prompt)
        else:
            return self._gerar_via_python(prompt)
    
    def _gerar_via_server(self, prompt: str) -> str:
        """Gera via llama-server (HTTP API)"""
        url = f"{self.config.server_url}/completion"
        
        payload = {
            "prompt": prompt,
            "n_predict": self.config.max_tokens,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "stop": ["</s>", "USUÁRIO:", "Human:"],
        }
        
        try:
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            return response.json().get("content", "")
        except Exception as e:
            print(f"❌ Erro ao chamar llama-server: {e}")
            return ""
    
    def _gerar_via_python(self, prompt: str) -> str:
        """Gera via llama-cpp-python"""
        client = self.client
        
        output = client(
            prompt,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            stop=["</s>", "USUÁRIO:", "Human:"],
            echo=False
        )
        
        return output["choices"][0]["text"]
    
    def _parse_verificacao(self, resposta: str) -> Dict:
        """Parse resposta de verificação"""
        try:
            # Extrai JSON da resposta
            json_match = re.search(r'\{[\s\S]*\}', resposta)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
        
        # Fallback
        return {
            "consistente": False,
            "justificativa": "Não foi possível parsear a resposta",
            "observacoes": [resposta[:500]],
            "sugestoes": []
        }
    
    def _parse_plano(self, resposta: str) -> Dict:
        """Parse resposta de plano"""
        try:
            json_match = re.search(r'\{[\s\S]*\}', resposta)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
        
        # Fallback
        return {
            "plano_sugerido": {
                "tipo_acao": "manual",
                "descricao": "Não foi possível gerar plano automático",
                "passos": [],
                "destinatarios": [],
                "prazo": "",
                "observacoes": resposta[:500]
            },
            "alternativas": [],
            "confianca": 0.0,
            "justificativa": "Erro ao parsear resposta"
        }


# =============================================================================
# EXEMPLO DE USO
# =============================================================================

def exemplo_verificacao():
    """Exemplo de verificação de consistência"""
    
    config = LlamaConfig(
        backend=LlamaBackend.SERVER,
        server_url="http://localhost:8080"
    )
    
    generator = QwenDocumentGenerator(config)
    
    comando = """
    INTIME-SE a parte ré, por via de seu advogado, para apresentar contestação 
    no prazo de 15 dias, sob pena de revelia.
    """
    
    cumprimento = """
    Email enviado para o advogado da parte ré (Dr. João Silva - OAB/BA 12345) 
    em 10/01/2026, com confirmação de leitura recebida em 11/01/2026.
    Juntada realizada no Projudi sob o evento 45.
    """
    
    resultado = generator.verificar_consistencia(comando, cumprimento)
    
    print("VERIFICAÇÃO DE CONSISTÊNCIA:")
    print(json.dumps(resultado, indent=2, ensure_ascii=False))


def exemplo_geracao_oficio():
    """Exemplo de geração de ofício"""
    
    config = LlamaConfig(
        backend=LlamaBackend.SERVER,
        server_url="http://localhost:8080"
    )
    
    generator = QwenDocumentGenerator(config)
    
    dados_processo = {
        'numero': '0001234-56.2025.8.05.0191',
        'partes': [
            {'nome': 'JOÃO DA SILVA', 'papel': 'AUTOR'},
            {'nome': 'MARIA SANTOS', 'papel': 'RÉ'},
        ],
        'comando_judicial': 'Intime-se a parte ré para pagar o débito em 3 dias.',
    }
    
    oficio = generator.gerar_oficio(dados_processo, tipo_oficio='intimacao')
    
    print("OFÍCIO GERADO:")
    print(oficio)


def exemplo_plano_cumprimento():
    """Exemplo de sugestão de plano"""
    
    config = LlamaConfig(
        backend=LlamaBackend.SERVER,
        server_url="http://localhost:8080"
    )
    
    generator = QwenDocumentGenerator(config)
    
    comando = "Oficie-se ao CEAPA solicitando informações sobre a situação do preso."
    
    dados_processo = {
        'numero': '0005678-90.2025.8.05.0191',
        'partes': [
            {'nome': 'MINISTÉRIO PÚBLICO', 'papel': 'AUTOR'},
            {'nome': 'JOÃO PRESO', 'papel': 'RÉ'},
        ]
    }
    
    cumprimentos_similares = [
        {
            'tipo_acao': 'email_enviado',
            'descricao': 'Email enviado ao CEAPA Paulo Afonso solicitando informações',
            'passos': ['Extrair email do CEAPA', 'Gerar ofício', 'Enviar email', 'Juntada no Projudi'],
            'status': 'concluido'
        },
        {
            'tipo_acao': 'oficio_gerado',
            'descricao': 'Ofício gerado e expedido via Projudi',
            'passos': ['Gerar ofício PDF', 'Anexar ao processo', 'Expedir'],
            'status': 'concluido'
        }
    ]
    
    plano = generator.sugerir_plano_cumprimento(comando, dados_processo, cumprimentos_similares)
    
    print("PLANO SUGERIDO:")
    print(json.dumps(plano, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    print("=" * 80)
    print("EXEMPLO 1: Verificação de Consistência")
    print("=" * 80)
    exemplo_verificacao()
    
    print("\n" + "=" * 80)
    print("EXEMPLO 2: Geração de Ofício")
    print("=" * 80)
    exemplo_geracao_oficio()
    
    print("\n" + "=" * 80)
    print("EXEMPLO 3: Sugestão de Plano de Cumprimento")
    print("=" * 80)
    exemplo_plano_cumprimento()
