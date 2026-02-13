import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
from datetime import datetime

st.set_page_config(page_title="Auditoría 360", layout="wide", page_icon="🔍")

conn = st.connection("supabase", type=SupabaseConnection)

st.title("🔍 Buscador de Auditoría Unificado por CIF")
st.markdown("---")

# --- MEMORIA DE SESIÓN (Persistencia entre años) ---
if "trabajadores_seleccionados" not in st.session_state:
    st.session_state.trabajadores_seleccionados = []
if "claves_seleccionadas" not in st.session_state:
    st.session_state.claves_seleccionadas = []

def limpiar_nif(texto):
    if not texto: return ""
    return str(texto).strip().upper().lstrip('0')

def obtener_alerta_idc(row_idc):
    """Cruza el estado de la BD con las fechas para explicar el 'Incompleto'."""
    if not row_idc:
        return "🔴 Sin IDC", "No se encontró registro"
    
    estado_bd = str(row_idc.get('estado', 'OK')).upper()
    inicio = row_idc.get('inicio_auditado')
    fin = row_idc.get('fin_auditado')
    
    if "INCOMPLETO" in estado_bd:
        try:
            # Convertimos fechas para dar un motivo legible
            f_ini = datetime.strptime(inicio, '%Y-%m-%d')
            f_fin = datetime.strptime(fin, '%Y-%m-%d')
            motivos = []
            if f_ini.month > 1: 
                motivos.append(f"falta Enero a {f_ini.strftime('%B')}")
            if f_fin.month < 12: 
                motivos.append(f"falta {f_fin.strftime('%B')} a Diciembre")
            
            detalle = "⚠️ Parcial: " + (" y ".join(motivos) if motivos else f"Periodo: {inicio} a {fin}")
            return "🟡 INCOMPLETO", detalle
        except:
            return "🟡 INCOMPLETO", f"Periodo parcial: {inicio} a {fin}"
    return "✅ OK", "Periodo completo"

try:
    # 1. CARGA DE EMPRESAS
    q_emp_190 = conn.table("modelo_190_central").select("nif_empresa, cliente").execute()
    q_emp_idc = conn.table("resumen_idcs_central").select("nif_empresa, cliente").execute()
    
    empresas_unificadas = {limpiar_nif(r['nif_empresa']): (r['cliente'] or "DESCONOCIDA").strip().upper() 
                          for r in (q_emp_190.data + q_emp_idc.data) if r.get('nif_empresa')}

    lista_opciones_empresa = sorted([f"{nombre} ({cif})" for cif, nombre in empresas_unificadas.items()])

    col1, col2 = st.columns(2)
    with col1:
        empresa_label = st.selectbox("🏢 Seleccionar Empresa:", options=lista_opciones_empresa)
        cif_sel = empresa_label.split('(')[-1].replace(')', '').strip()
        nombre_empresa_sel = empresa_label.split(' (')[0]
    with col2:
        anio_sel = st.selectbox("📅 Año:", [2025, 2024, 2023, 2026])

    # 2. CARGA DE TRABAJADORES (Filtro persistente)
    q_trab_190 = conn.table("modelo_190_central").select("nombre, nif").eq("nif_empresa", cif_sel).eq("ejercicio", anio_sel).execute()
    q_trab_idc = conn.table("resumen_idcs_central").select("nombre, nif").eq("nif_empresa", cif_sel).eq("ejercicio", anio_sel).execute()

    nifs_procesados = {limpiar_nif(r['nif']): r['nombre'].strip().upper() for r in (q_trab_190.data + q_trab_idc.data)}
    dict_trabajadores = {f"{nombre} ({nif})": nif for nif, nombre in nifs_procesados.items()}
    opciones_disponibles = sorted(list(dict_trabajadores.keys()))

    # Recuperar selección previa si existe en el nuevo año
    default_trab = [t for t in st.session_state.trabajadores_seleccionados if t in opciones_disponibles]
    st.session_state.trabajadores_seleccionados = st.multiselect("👤 Seleccionar Trabajadores:", options=opciones_disponibles, default=default_trab)

    # 3. SELECCIÓN DE CLAVES
    if st.session_state.trabajadores_seleccionados:
        nifs_lista = [dict_trabajadores[label] for label in st.session_state.trabajadores_seleccionados]
        res_claves = conn.table("modelo_190_central").select("clave").in_("nif", nifs_lista).eq("ejercicio", anio_sel).execute()
        claves_disponibles = sorted(list(set(d['clave'] for d in res_claves.data)))
        
        # Persistencia de claves
        default_claves = [c for c in st.session_state.claves_seleccionadas if c in claves_disponibles] or claves_disponibles
        st.session_state.claves_seleccionadas = st.multiselect("🎯 Claves para cálculo de Bruto:", options=claves_disponibles, default=default_claves)

        if st.button("📊 Analizar Situación"):
            st.divider()
            tab_resumen, tab_detalles = st.tabs(["📋 Tabla Resumen", "👤 Detalles Individuales"])
            lista_resumen = []

            with tab_detalles:
                for t_label in st.session_state.trabajadores_seleccionados:
                    nif_actual = dict_trabajadores[t_label]
                    nombre_actual = t_label.split(' (')[0]
                    
                    res_190 = conn.table("modelo_190_central").select("*").eq("nif", nif_actual).eq("ejercicio", anio_sel).execute()
                    res_idc = conn.table("resumen_idcs_central").select("*").eq("nif", nif_actual).eq("ejercicio", anio_sel).execute()

                    hay_190 = len(res_190.data) > 0
                    hay_idc = len(res_idc.data) > 0
                    
                    # Cálculo de Bruto filtrado
                    datos_190_filtrados = [d for d in res_190.data if d['clave'] in st.session_state.claves_seleccionadas]
                    bruto_final = sum(d.get('dinerarias_no_il', 0) + d.get('especie_no_il', 0) for d in datos_190_filtrados)
                    
                    # Datos IDC y Redondeo de Horas
                    horas_efec = 0
                    estado_idc_txt, motivo_idc_txt = obtener_alerta_idc(None)
                    
                    if hay_idc:
                        d_idc = res_idc.data[0]
                        # REDONDEO A 2 DECIMALES
                        horas_efec = round(float(d_idc.get('horas_efectivas', 0) or 0), 2)
                        estado_idc_txt, motivo_idc_txt = obtener_alerta_idc(d_idc)

                    coste_hora = round(bruto_final / horas_efec, 2) if horas_efec > 0 else 0

                    st.subheader(f"Análisis de {nombre_actual}")
                    
                    # Métricas con formato numérico limpio
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Salario Bruto", f"{bruto_final:,.2f} €")
                    c2.metric("Horas Efectivas (IDC)", f"{horas_efec:,.2f} h")
                    c3.metric("Coste Real Hora", f"{coste_hora:,.2f} €/h")

                    if estado_idc_txt == "🟡 INCOMPLETO":
                        st.warning(f"⚠️ **INFORMACIÓN PARCIAL**: {motivo_idc_txt}")

                    # Acumular para tabla resumen
                    lista_resumen.append({
                        "Nombre": nombre_actual,
                        "NIF": nif_actual,
                        "Bruto": f"{bruto_final:,.2f}€",
                        "Horas Efec.": horas_efec,
                        "Coste Hora": f"{coste_hora:,.2f}€/h",
                        "Estado IDC": estado_idc_txt,
                        "Alerta/Motivo": motivo_idc_txt,
                        "190": "✅" if hay_190 else "❌"
                    })

                    with st.expander(f"📝 Desglose Técnico de {nombre_actual}"):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.write("**Detalle AEAT**")
                            st.table(pd.DataFrame([{
                                "Suma": "➕" if d['clave'] in st.session_state.claves_seleccionadas else "➖",
                                "Clave": d['clave'],
                                "Dinerario": f"{d['dinerarias_no_il']:,.2f}€",
                                "Especie": f"{d['especie_no_il']:,.2f}€"
                            } for d in res_190.data]))
                        with col_b:
                            st.write("**Detalle IDC**")
                            if hay_idc:
                                st.write(f"**Estado:** {estado_idc_txt}")
                                st.write(f"**Periodo:** {motivo_idc_txt}")
                                st.write(f"**Horas IT:** {round(float(res_idc.data[0].get('horas_it', 0) or 0), 2)}h")
                            else: st.error("Sin datos de Seguridad Social")
                    st.markdown("---")

            with tab_resumen:
                st.subheader(f"Resumen General de Auditoría - {anio_sel}")
                df_final = pd.DataFrame(lista_resumen)
                
                # Asegurar que las horas se vean con 2 decimales en la tabla
                df_final["Horas Efec."] = df_final["Horas Efec."].map("{:,.2f}".format)
                
                # Función de estilo para colores
                def resaltar_problemas(s):
                    if s.name == 'Estado IDC':
                        return ['color: orange; font-weight: bold' if 'INCOMPLETO' in str(v) 
                                else 'color: red; font-weight: bold' if 'Sin' in str(v) 
                                else 'color: green' for v in s]
                    return [''] * len(s)

                st.dataframe(df_final.style.apply(resaltar_problemas), use_container_width=True)

except Exception as e:
    st.error(f"Error en la aplicación: {e}")