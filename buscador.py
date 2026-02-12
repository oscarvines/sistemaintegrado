import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection

st.set_page_config(page_title="Auditoría 360", layout="wide", page_icon="🔍")

conn = st.connection("supabase", type=SupabaseConnection)

st.title("🔍 Buscador de Auditoría Unificado por CIF")
st.markdown("---")

def limpiar_nif(texto):
    if not texto: return ""
    return str(texto).strip().upper().lstrip('0')

try:
    # 1. CARGAR EMPRESAS (UNIFICACIÓN POR CIF)
    q_emp_190 = conn.table("modelo_190_central").select("nif_empresa, cliente").execute()
    q_emp_idc = conn.table("resumen_idcs_central").select("nif_empresa, cliente").execute()
    
    # Unificamos: la clave es el CIF, el valor es el Nombre
    empresas_unificadas = {}
    for r in (q_emp_190.data + q_emp_idc.data):
        cif = limpiar_nif(r['nif_empresa'])
        nombre = r['cliente'].strip().upper() if r['cliente'] else "DESCONOCIDA"
        if cif and cif not in empresas_unificadas:
            empresas_unificadas[cif] = nombre

    # Creamos la lista para el selectbox: "NOMBRE (CIF)"
    lista_opciones_empresa = sorted([f"{nombre} ({cif})" for cif, nombre in empresas_unificadas.items()])

    col1, col2 = st.columns(2)
    with col1:
        empresa_label = st.selectbox("🏢 Seleccionar Empresa:", options=lista_opciones_empresa)
        # Extraemos el CIF del label (lo que está entre paréntesis)
        cif_sel = empresa_label.split('(')[-1].replace(')', '').strip()
    with col2:
        anio_sel = st.selectbox("📅 Año:", [2025, 2024, 2023, 2026])

    # 2. CARGAR TRABAJADORES (De ambas fuentes)
    q_trab_190 = conn.table("modelo_190_central").select("nombre, nif").eq("nif_empresa", cif_sel).eq("ejercicio", anio_sel).execute()
    q_trab_idc = conn.table("resumen_idcs_central").select("nombre, nif").eq("nif_empresa", cif_sel).eq("ejercicio", anio_sel).execute()

    dict_trabajadores = {}
    for r in (q_trab_190.data + q_trab_idc.data):
        nif_l = limpiar_nif(r['nif'])
        nombre_l = r['nombre'].strip().upper()
        dict_trabajadores[f"{nombre_l} ({nif_l})"] = nif_l

    if not dict_trabajadores:
        st.warning(f"No hay ningún dato para el CIF {cif_sel} en {anio_sel}.")
    else:
        trab_label = st.selectbox("👤 Seleccionar Trabajador:", options=sorted(list(dict_trabajadores.keys())))
        nif_sel = dict_trabajadores[trab_label]

        if st.button("📊 Analizar Situación"):
            res_190 = conn.table("modelo_190_central").select("*").eq("nif", nif_sel).eq("ejercicio", anio_sel).execute()
            res_idc = conn.table("resumen_idcs_central").select("*").eq("nif", nif_sel).eq("ejercicio", anio_sel).execute()

            hay_190 = len(res_190.data) > 0
            hay_idc = len(res_idc.data) > 0

            st.divider()

            if hay_190 and hay_idc:
                st.success("✅ Auditoría Completa")
                d1, d2 = res_190.data[0], res_idc.data[0]
                bruto = d1.get('dinerarias_no_il', 0) + d1.get('especie_no_il', 0)
                horas = d2.get('horas_efectivas', 0)
                coste = bruto / horas if horas > 0 else 0
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Salario Bruto", f"{bruto:,.2f} €")
                c2.metric("Horas Efectivas", f"{horas:,.2f} h")
                c3.metric("Coste Real Hora", f"{coste:,.2f} €/h")

            elif hay_190:
                st.warning("⚠️ Falta IDC (Seguridad Social)")
                d1 = res_190.data[0]
                st.metric("Salario Bruto Detectado", f"{d1.get('dinerarias_no_il', 0):,.2f} €")
            
            elif hay_idc:
                st.warning("⚠️ Falta Modelo 190 (AEAT)")
                d2 = res_idc.data[0]
                st.metric("Horas Efectivas Detectadas", f"{d2.get('horas_efectivas', 0)} h")

            # --- DESGLOSE EN TABLAS (SIN CÓDIGOS) ---
            with st.expander("📝 Detalle de registros encontrados"):
                col_a, col_b = st.columns(2)
                with col_a:
                    st.subheader("🏦 Datos AEAT")
                    if hay_190:
                        d = res_190.data[0]
                        st.table(pd.DataFrame({
                            "Concepto": ["Salario Dinerario", "Salario Especie", "Clave", "Archivo"],
                            "Valor": [f"{d['dinerarias_no_il']:,.2f}€", f"{d['especie_no_il']:,.2f}€", d['clave'], d['archivo_origen']]
                        }))
                    else:
                        st.error("No hay datos en el Modelo 190")

                with col_b:
                    st.subheader("🛡️ Datos Seguridad Social")
                    if hay_idc:
                        d = res_idc.data[0]
                        
                        # Recuperamos el CTP de la base de datos y lo formateamos
                        # Si es 0 o 1000 es 100%, si no, dividimos por 10
                        ctp_bd = d.get('ctp', 0)
                        dedicacion_formateada = f"{ctp_bd / 10}%" if ctp_bd > 0 else "100%"

                        st.table(pd.DataFrame({
                            "Concepto": ["Dedicación (CTP)", "Horas Efectivas", "Horas IT", "Días IT", "Estado"],
                            "Valor": [
                                dedicacion_formateada, 
                                f"{d['horas_efectivas']}h", 
                                f"{d['horas_it']}h", 
                                d['dias_it'], 
                                d['estado']
                            ]
                        }))
                    else:
                        st.error("No hay datos de IDC subidos")

except Exception as e:
    st.error(f"Error: {e}")