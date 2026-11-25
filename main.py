"""Chat con Dear Skin desde la consola (sin web), viendo qué hace cada nodo del grafo.

Uso:
    python main.py
    python main.py "Tengo piel mixta y sensible, granitos en la frente, quiero más luminosidad. \
Ya tengo hidratante, presupuesto 50 € y no quiero diez pasos"
    python main.py --usuario u-1a2b3c4d "¿Merece la pena el PDRN de medicube?"
"""

import asyncio
import sys

from app import rutina
from app.agentes import herramientas_mcp
from app.grafo import construir_grafo, entrada_turno


async def main() -> None:
    args = sys.argv[1:]
    usuario = ""
    if len(args) >= 2 and args[0] == "--usuario":
        usuario, args = args[1], args[2:]
    primera = " ".join(args)
    config = {"configurable": {"thread_id": usuario or "consola"}}
    async with herramientas_mcp() as herramientas:
        grafo = construir_grafo(herramientas)
        while True:
            pregunta = primera or input("\nTú (Enter vacío para salir): ").strip()
            primera = ""
            if not pregunta:
                break
            async for paso in grafo.astream(entrada_turno(pregunta, usuario), config, stream_mode="updates"):
                for nodo, cambios in paso.items():
                    if nodo == "cargar_usuario":
                        continue
                    if nodo == "supervisor" and cambios["siguiente"] == "FIN":
                        print("  [supervisor] Ya hay información suficiente.")
                    elif nodo == "supervisor":
                        print(f"  [supervisor] -> {cambios['siguiente']}: {cambios['tarea'][:150]}")
                    elif nodo == "personal_shopper":
                        print("\n" + rutina.resumen_texto(cambios["rutina"]) + "\n")
                    elif nodo == "responder":
                        print(f"\nTez: {cambios['messages'][-1].text}")
                    else:
                        print(f"  {cambios['hallazgos'][-1][:200]}...")


if __name__ == "__main__":
    asyncio.run(main())
