import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection

st.set_page_config(page_title="Dashboard Auditoría Laboral", layout="wide", page_icon="📊")

# --- CONEXIÓN A SUPABASE ---
conn = st.connection("supabase", type=SupabaseConnection)

st.title("📊 Panel de Auditoría Consolidada (Búsqueda por CIF)")
st.markdown("---")

# --- FUNCIONES DE LIMPIEZA ---
def limpiar_nif(texto):
    if not texto: return ""
    return str(texto).strip().upper().lstrip('0')

try:
    # 1. OBTENER EMPRESAS (Agrupadas por CIF para evitar duplicados por nombre)
    query_emp = conn.table("resumen_idcs_central").select("nif_empresa, cliente").execute()
    
    if query_emp.data:
        # Creamos un diccionario: { "NOMBRE EMPRESA (CIF)": "CIF_LIMPIO" }
        # Usamos un set para evitar nombres repetidos si hay muchos trabajadores
        dict_empresas = {}
        for r in query_emp.data:
            cif = limpiar_nif(r['nif_empresa'])
            nombre = r['cliente'].strip().upper() if r['cliente'] else "DESCONOCIDA"
            if cif:
                dict_empresas[f"{nombre} ({cif})"] = cif

        col1, col2 = st.columns(2)
        with col1:
            empresa_label = st.selectbox("🏢 Seleccionar Empresa:", options=sorted(list(dict_empresas.keys())))
            cif_seleccionado = dict_empresas[empresa_label]
        with col2:
            anio_sel = st.selectbox("📅 Ejercicio Fiscal:", [2026, 2025, 2024, 2023, 2022])

        # 2. FILTRAR TRABAJADORES POR CIF Y AÑO
        # Buscamos en la tabla de IDCs todos los que pertenezcan a ese CIF de empresa
        q_trab = conn.table("resumen_idcs_central").select("nombre, nif") \
                     .eq("nif_empresa", cif_seleccionado) \
                     .eq("ejercicio", anio_sel).execute()

        if not q_trab.data:
            st.warning(f"No se han encontrado trabajadores para el CIF {cif_seleccionado} en el año {anio_sel}.")
        else:
            # Diccionario de trabajadores: { "NOMBRE (NIF)": "NIF_LIMPIO" }
            dict_trabajadores = {f"{r['nombre']} ({limpiar_nif(r['nif'])})": limpiar_nif(r['nif']) for r in q_trab.data}
            
            trabajador_label = st.selectbox("👤 Seleccionar Trabajador:", options=sorted(list(dict_trabajadores.keys())))
            nif_trabajador = dict_trabajadores[trabajador_label]

            # 3. GENERAR INFORME CRUZADO
            if st.button("🔍 Generar Informe de Auditoría"):
                # Consulta a las dos tablas clave usando el NIF del trabajador y el año
                res_190 = conn.table("modelo_190_central").select("*").eq("nif", nif_trabajador).eq("ejercicio", anio_sel).execute()
                res_idc = conn.table("resumen_idcs_central").select("*").eq("nif", nif_trabajador).eq("ejercicio", anio_sel).execute()

                if not res_190.data:
                    st.error(f"Faltan datos del Modelo 190 (AEAT) para el NIF {nif_trabajador} en {anio_sel}.")
                elif not res_idc.data:
                    st.error(f"Faltan datos del IDC (Seguridad Social) para el NIF {nif_trabajador} en {anio_sel}.")
                else:
                    # PROCESAMIENTO
                    d190 = res_190.data[0]
                    didc = res_idc.data[0]

                    # Cálculo de ingresos totales (Dinerarias + Especie)
                    salario_bruto = (d190.get('dinerarias_no_il', 0) + d190.get('especie_no_il', 0) +
                                    d190.get('dinerarias_il', 0) + d190.get('especie_il', 0))
                    
                    horas_efectivas = didc.get('horas_efectivas', 0)
                    coste_hora = salario_bruto / horas_efectivas if horas_efectivas > 0 else 0

                    # VISUALIZACIÓN
                    st.divider()
                    st.subheader(f"Informe de Auditoría: {d190['nombre']}")
                    
                    if didc['estado'] == "⚠️ INCOMPLETO":
                        st.warning(f"⚠️ **DATOS PARCIALES:** Solo hay información desde {didc['inicio_auditado']}. El coste/hora real será más alto.")

                    c1, c2, c3 = st.columns(3)
                    c1.metric("Ingresos Totales (AEAT)", f"{salario_bruto:,.2f} €")
                    c2.metric("Horas Efectivas (SS)", f"{horas_efectivas:,.2f} h")
                    c3.metric("Coste Real / Hora", f"{coste_hora:,.2f} €/h")

                    ## DETALLES ADICIONALES (Formato Humano)
                    with st.expander("📝 Ver desglose detallado de la auditoría"):
                        col_aeat, col_ss = st.columns(2)
                        
                        with col_aeat:
                            st.markdown("### 🏦 Datos AEAT (Modelo 190)")
                            datos_aeat = {
                                "Concepto": ["Salario Dinerario", "Salario en Especie", "Clave Percebe", "Archivo Origen", "CIF Empresa"],
                                "Valor": [
                                    f"{d190.get('dinerarias_no_il', 0):,.2f} €",
                                    f"{d190.get('especie_no_il', 0):,.2f} €",
                                    f"{d190.get('clave', '')}{d190.get('subclave', '')}",
                                    d190.get('archivo_origen', 'N/A'),
                                    d190.get('nif_empresa', '')
                                ]
                            }
                            st.table(pd.DataFrame(datos_aeat))

                        with col_ss:
                            st.markdown("### 🛡️ Datos Seg. Social (IDC)")
                            datos_ss = {
                                "Concepto": ["Horas Efectivas", "Horas IT (Baja)", "Días de Baja", "Inicio Contrato", "Estado IDC"],
                                "Valor": [
                                    f"{didc.get('horas_efectivas', 0)} h",
                                    f"{didc.get('horas_it', 0)} h",
                                    f"{didc.get('dias_it', 0)} días",
                                    didc.get('inicio_contrato', 'N/A'),
                                    didc.get('estado', 'N/A')
                                ]
                            }
                            st.table(pd.DataFrame(datos_ss))
                        
                        st.info(f"💡 **Nota de integridad:** Los datos han sido cruzados mediante el NIF {nif_trabajador}. "
                                f"Aunque los nombres varíen en los documentos, el identificador único garantiza la precisión.")
    else:
        st.info("La base de datos de IDCs está vacía. Por favor, sincroniza datos primero.")

except Exception as e:
    st.error(f"Se ha producido un error al consultar Supabase: {e}")