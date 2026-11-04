"""Preenchimento por voz: a conversão do que foi falado em cada tipo de campo (voz.js, via Node)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

VOZ = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "voz.js"

CASOS = [
    ("data", "doze de março de mil novecentos e setenta", "12/03/1970"),
    ("data", "primeiro de janeiro de dois mil e cinco", "01/01/2005"),
    ("data", "5 de outubro de 80", "05/10/1980"),
    ("data", "12 03 1970", "12/03/1970"),
    ("diames", "vinte de outubro", "20/10"),
    ("hora", "sete e meia da noite", "19:30"),
    ("hora", "dezenove horas e quinze", "19:15"),
    ("telefone", "sessenta e dois nove nove oito sete seis cinco quatro três dois", "62998765432"),
    ("telefone", "meia dois nove nove meia meia meia meia meia meia meia", "62996666666"),
    ("telefone", "9 8765 4321", "62987654321"),
    ("cpf", "cinco dois nove nove oito dois dois quatro sete dois cinco", "52998224725"),
    ("email", "maria ponto souza arroba gmail ponto com", "maria.souza@gmail.com"),
    ("email", "ana traço paula 2 arroba yahoo ponto com ponto br", "ana-paula2@yahoo.com.br"),
    ("nome", "MARIA DA SILVA DOS SANTOS", "Maria da Silva dos Santos"),
    ("cidade", "goiânia goiás", "Goiânia - GO"),
    ("moeda", "cinquenta reais e vinte centavos", "50,20"),
    ("moeda", "mil e duzentos reais", "1200,00"),
    ("codigo", "k 7 p 3 q x", "K7P3QX"),
    ("arquivo", "maria da silva souza ponto pdf", "Maria da Silva Souza.pdf"),
    ("texto", "mudou de cidade vírgula pediu desligamento ponto final não congrega mais",
     "Mudou de cidade, pediu desligamento. Não congrega mais"),
]


def _rodar(codigo):
    if not shutil.which("node"):
        pytest.skip("Node não instalado")
    saida = subprocess.run(["node", "-e", f"const v=require({json.dumps(str(VOZ))});{codigo}"],
                           capture_output=True, text=True, check=True)
    return json.loads(saida.stdout)


def test_conversao_por_tipo_de_campo():
    js = "console.log(JSON.stringify(%s.map(([t,x])=>v.NORMALIZAR[t](x).valor)))" % json.dumps([[t, x] for t, x, _ in CASOS])
    assert _rodar(js) == [esperado for _, _, esperado in CASOS]


def test_escolhe_a_interpretacao_valida():
    # o navegador ouviu dois CPFs parecidos: fica com o que tem os dígitos verificadores certos
    r = _rodar("console.log(JSON.stringify(v.melhor(['529 982 247 26', '529 982 247 25'], 'cpf')))")
    assert r == {"valor": "52998224725", "ok": True}
    r = _rodar("console.log(JSON.stringify(v.melhor(['31 de fevereiro de 1990', '21 de fevereiro de 1990'], 'data')))")
    assert r["valor"] == "21/02/1990"
