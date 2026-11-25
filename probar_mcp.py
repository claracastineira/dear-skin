"""Prueba el servidor MCP sin agentes ni LLM: lista sus herramientas y llama a cada una.

Uso:
    python probar_mcp.py
"""

import asyncio

from fastmcp import Client

from app.servidor_mcp import servidor


async def main() -> None:
    # Client(servidor) conecta con el servidor en memoria, sin lanzar otro proceso
    async with Client(servidor) as cliente:
        herramientas = await cliente.list_tools()
        print("Herramientas:", [h.name for h in herramientas])

        pruebas = [
            ("buscar_productos", {"consulta": "sérum para manchas", "zona": "cara",
                                  "precio_min": 15, "precio_max": 30, "solo_coreano": True}),
            ("explicar_ingrediente", {"consulta": "¿Qué es el retinol?"}),
            ("ver_resenas", {"producto_id": "boj-relief-sun", "tipo_piel": "mixta"}),
            ("generar_rutina", {"tipo_piel": "mixta", "sensible": True, "objetivos": ["acne", "luminosidad"],
                                "presupuesto": 50, "max_pasos": 4, "ya_tengo": ["hidratante"]}),
            ("merece_la_pena", {"producto": "medicube PDRN pink peptide serum"}),
        ]
        for nombre, argumentos in pruebas:
            resultado = await cliente.call_tool(nombre, argumentos)
            print(f"\n=== {nombre} {argumentos}\n{resultado.content[0].text[:800]}")


if __name__ == "__main__":
    asyncio.run(main())
