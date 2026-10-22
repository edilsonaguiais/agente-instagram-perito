"""Página de venda de cada produto, com preço e QR Code do Pix, servida pelo próprio agente.

Cada página é um arquivo `conhecimento/paginas/<endereço>.md`:

    titulo: Laudo Blindado
    preco: 997,00
    subtitulo: Revisão técnica profunda do laudo que você já fez
    ---
    Texto livre. Linhas com "## " viram título; linhas com "- " viram lista.

Fica em https://SEU_DOMINIO/p/<endereço>. O Pix usa PIX_CHAVE, PIX_NOME e PIX_CIDADE do .env.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import qrcode
import qrcode.image.svg

RE_ENDERECO = re.compile(r"[a-z0-9][a-z0-9-]{0,60}")


@dataclass
class Pagina:
    endereco: str
    titulo: str
    preco: Decimal
    subtitulo: str
    corpo: str


def _campo(id_: str, valor: str) -> str:
    return f"{id_}{len(valor):02d}{valor}"


def _crc16(dados: str) -> str:
    crc = 0xFFFF
    for byte in dados.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def _ascii(texto: str, limite: int) -> str:
    """O BR Code aceita só ASCII simples no nome e na cidade."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9 ]", "", sem_acento).strip().upper()[:limite]


def pix_copia_e_cola(chave: str, valor: Decimal, nome: str, cidade: str, txid: str = "***") -> str:
    """Pix estático (BR Code do Banco Central) com valor fixo."""
    conta = _campo("00", "br.gov.bcb.pix") + _campo("01", chave.strip())
    corpo = (_campo("00", "01") + _campo("26", conta) + _campo("52", "0000") + _campo("53", "986")
             + _campo("54", f"{valor:.2f}") + _campo("58", "BR") + _campo("59", _ascii(nome, 25))
             + _campo("60", _ascii(cidade, 15)) + _campo("62", _campo("05", txid[:25])) + "6304")
    return corpo + _crc16(corpo)


def qr_svg(texto: str) -> str:
    imagem = qrcode.make(texto, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    svg = imagem.to_string(encoding="unicode")
    return re.sub(r"<\?xml[^>]*\?>", "", svg)


def endereco_de(titulo: str) -> str:
    """"Análise prévia de contrato" -> "analise-previa-de-contrato"."""
    sem_acento = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", sem_acento).strip("-")[:60]


def paginas_dos_servicos(pasta: Path) -> dict[str, Pagina]:
    """Cada "## Serviço" do servicos.md com a linha "- Pix: 350,00" ganha uma página sozinho."""
    arquivo = pasta / "servicos.md"
    if not arquivo.exists():
        return {}
    paginas = {}
    for bloco in re.split(r"^## ", arquivo.read_text(encoding="utf-8"), flags=re.M)[1:]:
        titulo, _, corpo = bloco.partition("\n")
        pix = re.search(r"^- Pix:\s*([\d.]+,\d{2})\s*$", corpo, re.M)
        if not pix:
            continue
        try:
            preco = Decimal(pix.group(1).replace(".", "").replace(",", "."))
        except InvalidOperation:
            continue
        o_que = re.search(r"^- O que é:\s*(.+(?:\n  .+)*)", corpo, re.M)
        subtitulo = re.sub(r"\s+", " ", o_que.group(1)) if o_que else ""
        endereco = endereco_de(titulo.strip())
        linhas = [l for l in corpo.splitlines() if l.startswith("- ") and not l.startswith(("- Pix:", "- O que é:"))]
        paginas[endereco] = Pagina(endereco, titulo.strip(), preco, subtitulo, "\n".join(linhas))
    return paginas


def ler_pagina(pasta: Path, endereco: str) -> Pagina | None:
    if not RE_ENDERECO.fullmatch(endereco):
        return None
    arquivo = pasta / "paginas" / f"{endereco}.md"
    if not arquivo.exists():
        return paginas_dos_servicos(pasta).get(endereco)
    cabeca, _, corpo = arquivo.read_text(encoding="utf-8").partition("\n---\n")
    campos = {}
    for linha in cabeca.splitlines():
        if ":" in linha:
            chave, valor = linha.split(":", 1)
            campos[chave.strip().lower()] = valor.strip()
    try:
        preco = Decimal(campos.get("preco", "").replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None
    return Pagina(endereco, campos.get("titulo", endereco), preco, campos.get("subtitulo", ""), corpo.strip())


def _corpo_html(texto: str) -> str:
    partes, lista = [], []

    def fechar_lista():
        if lista:
            partes.append("<ul>" + "".join(f"<li>{i}</li>" for i in lista) + "</ul>")
            lista.clear()

    for linha in texto.splitlines():
        linha = linha.strip()
        if linha.startswith("- "):
            lista.append(html.escape(linha[2:]))
            continue
        fechar_lista()
        if linha.startswith("## "):
            partes.append(f"<h2>{html.escape(linha[3:])}</h2>")
        elif linha:
            partes.append(f"<p>{html.escape(linha)}</p>")
    fechar_lista()
    return "\n".join(partes)


def brl(valor: Decimal) -> str:
    inteiro, centavos = f"{valor:.2f}".split(".")
    return f"R$ {int(inteiro):,}".replace(",", ".") + f",{centavos}"


def renderizar(p: Pagina, dono: str, pix_chave: str, pix_nome: str, pix_cidade: str) -> str:
    codigo = pix_copia_e_cola(pix_chave, p.preco, pix_nome or dono, pix_cidade or "BRASIL",
                              txid=re.sub(r"[^A-Za-z0-9]", "", p.endereco.upper())[:25] or "***")
    e = html.escape
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(p.titulo)} — {e(dono)}</title>
<style>
:root{{--fundo:#f6f4ef;--texto:#1d232b;--suave:#5b6470;--marca:#0f3d5e;--cartao:#fff;--borda:#ddd8cc}}
@media (prefers-color-scheme:dark){{:root{{--fundo:#11161c;--texto:#e8eaed;--suave:#a3acb7;--marca:#7fb6dd;--cartao:#1a2129;--borda:#2c3540}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--fundo);color:var(--texto);font:17px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:680px;margin:0 auto;padding:32px 16px 64px}}
.dono{{color:var(--suave);font-size:14px;letter-spacing:.04em;text-transform:uppercase}}
h1{{font-size:32px;line-height:1.2;margin:8px 0 4px;color:var(--marca)}}
.sub{{color:var(--suave);font-size:19px;margin:0 0 24px}}
h2{{font-size:20px;margin:28px 0 8px}}ul{{padding-left:22px}}li{{margin:4px 0}}
.pagar{{background:var(--cartao);border:1px solid var(--borda);border-radius:14px;padding:24px;margin-top:36px;text-align:center}}
.preco{{font-size:34px;font-weight:700;color:var(--marca);margin:4px 0 16px}}
.qr{{background:#fff;display:inline-block;padding:8px;border-radius:8px}}.qr svg{{width:220px;height:220px;display:block}}
textarea{{width:100%;margin-top:16px;font:13px/1.4 ui-monospace,monospace;padding:10px;border-radius:8px;border:1px solid var(--borda);background:var(--fundo);color:var(--texto);resize:none;word-break:break-all}}
button{{margin-top:10px;background:var(--marca);color:#fff;border:0;border-radius:10px;padding:12px 20px;font-size:16px;cursor:pointer}}
.obs{{color:var(--suave);font-size:14px;margin-top:16px}}
</style></head><body><main>
<div class="dono">{e(dono)}</div>
<h1>{e(p.titulo)}</h1>
<p class="sub">{e(p.subtitulo)}</p>
{_corpo_html(p.corpo)}
<section class="pagar" id="pagar">
<div>Investimento</div>
<div class="preco">{brl(p.preco)}</div>
<div class="qr" role="img" aria-label="QR Code do Pix">{qr_svg(codigo)}</div>
<p>Aponte a câmera do app do seu banco ou use o Pix copia e cola:</p>
<textarea id="pix" rows="4" readonly>{e(codigo)}</textarea>
<button onclick="navigator.clipboard.writeText(document.getElementById('pix').value).then(()=>this.textContent='Copiado')">Copiar código Pix</button>
<p class="obs">Chave Pix: {e(pix_chave)}. Pagou? Mande o comprovante no direct para a gente combinar o início.</p>
</section>
</main></body></html>"""
