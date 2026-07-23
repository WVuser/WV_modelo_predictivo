import os
import pandas as pd
import time
from datetime import datetime
from hubspot import HubSpot
from hubspot.crm.contacts import PublicObjectSearchRequest, Filter, FilterGroup
from hubspot.crm.associations import BatchInputPublicObjectId, PublicObjectId
from hubspot.crm.objects import BatchReadInputSimplePublicObjectId, SimplePublicObjectId

# --- CONFIGURACIÓN ---
HS_ACCESS_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN")
if not HS_ACCESS_TOKEN:
    raise ValueError("La variable de entorno HUBSPOT_ACCESS_TOKEN no está configurada.")

OBJECT_TYPE_PAGOS = "2-31431979" 
PROPIEDAD_METODO_PAGO = "metodos_de_pago" 
PROPIEDAD_CAPTOR_DEAL = "cl___captor" 
PROPIEDAD_ESTADO_COBRO = "estado_cobro__clonada_"
PROPIEDAD_CLOSE_DATE = "closedate"

# --- MODO DE EJECUCIÓN ---
# True: Descarga solo 100 contactos para testear el flujo. 
# False: Descarga la base de datos completa.
MODO_PRUEBA = True 

def generar_reporte_todo_chile(modo_prueba=True):
    client = HubSpot(access_token=HS_ACCESS_TOKEN)
    inicio_total = time.time()
    hoy = datetime.now()
    
    # --- NUEVA FUNCIÓN: Transformar fechas a días transcurridos para el modelo ---
    def calcular_dias(valor_fecha):
        if not valor_fecha or pd.isna(valor_fecha) or valor_fecha == "N/A":
            return "N/A"
        try:
            if str(valor_fecha).isdigit():
                dt = datetime.fromtimestamp(int(valor_fecha) / 1000)
            else:
                dt = datetime.strptime(str(valor_fecha)[:10], "%Y-%m-%d")
            dias = (hoy - dt).days
            return dias if dias >= 0 else 0
        except:
            return "N/A"

    mapeo_metodos = {
        "CHLO-4": "CL - Multibanca",
        "CHLO-2": "CL - Payku",
        "CHLO-3": "CL - Tarjeta de Crédito",
        "CHLO-5": "CL - Depósito",
        "CHLO-120": "CL - Transferencia",
        "CHLO-118": "CL - Botón de pago", 
        "19": "CL - Multibanca",
        "CL - VirtualPOS": "CL - VirtualPOS",
        "ch_transbank": "CL - Transbank"
    }

    # 0. MAPEO AUTOMÁTICO DE PIPELINES DESDE LA API
    print("0. Obteniendo mapeo automático de etapas (Pipelines) desde HubSpot...")
    mapeo_pipelines_dinamico = {}
    try:
        pipelines_res = client.crm.pipelines.pipelines_api.get_all(object_type=OBJECT_TYPE_PAGOS)
        for pipeline in pipelines_res.results:
            for stage in pipeline.stages:
                mapeo_pipelines_dinamico[str(stage.id)] = stage.label
        print(f"--- Se mapearon automáticamente {len(mapeo_pipelines_dinamico)} etapas reales ---\n")
    except Exception as e:
        print(f"\nError al obtener mapeo automático: {e}")
        return

    # 1. BUSCAR CONTACTOS
    print(f"1. Iniciando búsqueda masiva de contactos de Chile (Modo Prueba: {modo_prueba})...")
    
    filtro_pais_base = Filter(property_name="prospecto", operator="EQ", value="Prospecto World Vision Chile")
    req_total = PublicObjectSearchRequest(
        filter_groups=[FilterGroup(filters=[filtro_pais_base])], 
        limit=1
    )
    
    try:
        search_total = client.crm.contacts.search_api.do_search(public_object_search_request=req_total)
        total_esperado = search_total.total
        print(f"Total de contactos a extraer según HubSpot: {total_esperado}\n")
    except Exception as e:
        print(f"No se pudo obtener el total inicial. Error: {e}")
        total_esperado = 1 

    contactos_dict = {}
    last_id = 0
    has_more = True
    
    propiedades_contacto = [
        "email", 
        "hs_analytics_num_visits", 
        "hs_analytics_num_page_views",
        "hs_analytics_first_visit_timestamp",
        "hs_analytics_last_visit_timestamp",
        "hs_email_sended_count",
        "hs_email_open_count",
        "hs_email_click_count",
        "hs_email_bounce_count"
    ]
    
    while has_more:
        filtro_pais = Filter(property_name="prospecto", operator="EQ", value="Prospecto World Vision Chile")
        filtro_id = Filter(property_name="hs_object_id", operator="GT", value=str(last_id))
        grupo_filtros = FilterGroup(filters=[filtro_pais, filtro_id])
        
        req = PublicObjectSearchRequest(
            filter_groups=[grupo_filtros], 
            properties=propiedades_contacto, 
            limit=100, 
            sorts=["hs_object_id"]
        )
        
        try:
            search = client.crm.contacts.search_api.do_search(public_object_search_request=req)
            if not search.results: 
                break
                
            for c in search.results: 
                contactos_dict[c.id] = c.properties
                    
            last_id = int(search.results[-1].id)
            print(f"Descargando Contactos... {len(contactos_dict)} registros obtenidos.")
            
            # --- LÓGICA DEL MODO PRUEBA ---
            if modo_prueba:
                print("--- Modo prueba activado: Deteniendo la paginación a los 100 contactos ---")
                break
            
            if len(search.results) < 100: 
                has_more = False
                
        except Exception as e:
            print(f"\nError en búsqueda masiva: {e}")
            break
            
    contact_ids = list(contactos_dict.keys())
    total_contactos = len(contact_ids)
    print(f"\n--- Búsqueda finalizada: {total_contactos} contactos cargados correctamente ---\n")

    if not contact_ids:
        print("No se encontraron contactos para procesar.")
        return

    # 2. PROCESAR ASOCIACIONES CONTACTO -> PAGOS
    print("2. Procesando asociaciones de Pagos a los contactos...")
    pago_to_contacto = {}
    
    for i in range(0, total_contactos, 100):
        lote = contact_ids[i:i+100]
        assoc_pagos = client.crm.associations.batch_api.read(
            "contact", OBJECT_TYPE_PAGOS, 
            BatchInputPublicObjectId(inputs=[PublicObjectId(id=cid) for cid in lote])
        )
        for res in assoc_pagos.results:
            for p in res.to: 
                pago_to_contacto[str(p.id)] = res._from.id
                
        print(f"Asociación Contacto->Pagos en progreso... Lote {i} procesado.")
        time.sleep(0.1)
        
    pago_ids = list(pago_to_contacto.keys())
    total_pagos = len(pago_ids)
    print(f"\n--- Se encontraron {total_pagos} pagos totales para la base extraída ---\n")

    if total_pagos == 0:
        print("No hay pagos para consolidar.")
        return

    # 3. PROCESAR ASOCIACIONES PAGO -> DEAL
    print("3. Cruzando cada Pago con su Deal específico (Prevención de sobreescritura)...")
    pagos_a_deal = {}
    
    for i in range(0, total_pagos, 100):
        lote_p = pago_ids[i:i+100]
        assoc_deals = client.crm.associations.batch_api.read(
            OBJECT_TYPE_PAGOS, "deal", 
            BatchInputPublicObjectId(inputs=[PublicObjectId(id=pid) for pid in lote_p])
        )
        for res in assoc_deals.results:
            if res.to:
                pagos_a_deal[str(res._from.id)] = str(res.to[0].id)
                
        print(f"Asociando Pagos->Deals... Lote {i} procesado.")
        time.sleep(0.1)
    
    deal_ids_unicos = list(set(pagos_a_deal.values()))
    print(f"\n--- Se identificaron {len(deal_ids_unicos)} Deals únicos en total ---\n")

    # 4. DESCARGAR INFORMACIÓN DE LOS DEALS
    print("4. Descargando datos de captor y fechas de todos los Deals implicados...")
    datos_deal_dict = {}
    
    if deal_ids_unicos:
        for i in range(0, len(deal_ids_unicos), 100):
            lote_d = deal_ids_unicos[i:i+100]
            deals_res = client.crm.objects.batch_api.read(
                "deal", 
                BatchReadInputSimplePublicObjectId(
                    properties=[PROPIEDAD_CAPTOR_DEAL, PROPIEDAD_ESTADO_COBRO, PROPIEDAD_CLOSE_DATE], 
                    inputs=[SimplePublicObjectId(id=did) for did in lote_d]
                )
            )
            for d in deals_res.results:
                raw_close_date = d.properties.get(PROPIEDAD_CLOSE_DATE)
                close_date_legible = "N/A"
                if raw_close_date and raw_close_date != "N/A":
                    try:
                        close_date_legible = datetime.fromtimestamp(int(raw_close_date)/1000).strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        close_date_legible = raw_close_date

                datos_deal_dict[str(d.id)] = {
                    "captor": d.properties.get(PROPIEDAD_CAPTOR_DEAL, "No asignado"),
                    "estado": d.properties.get(PROPIEDAD_ESTADO_COBRO, "Sin estado"),
                    "close_date": close_date_legible,
                    "raw_close_date": raw_close_date # Añadido para el modelo predictivo
                }
            print(f"Extrayendo info Deals... Lote {i} procesado.")
            time.sleep(0.1)
    print("\n--- Descarga de información de Deals finalizada ---\n")

    # 5. CONSOLIDAR TODO EL REPORTE
    print(f"5. Consolidando la totalidad de los {total_pagos} registros finales...")
    data = []
    
    for i in range(0, total_pagos, 100):
        lote_pagos = pago_ids[i:i+100]
        pagos_res = client.crm.objects.batch_api.read(
            OBJECT_TYPE_PAGOS, 
            BatchReadInputSimplePublicObjectId(
                # SE AÑADIERON hs_createdate y hs_lastmodifieddate
                properties=["fecha_de_pago", "amount", "hs_pipeline_stage", "nombre_del_pago", PROPIEDAD_METODO_PAGO, "hs_createdate", "hs_lastmodifieddate"], 
                inputs=[SimplePublicObjectId(id=pid) for pid in lote_pagos]
            )
        )
        
        for p in pagos_res.results:
            pid = str(p.id)
            cid = pago_to_contacto.get(pid)
            contacto_info = contactos_dict.get(cid, {}) if cid else {}
            
            deal_asociado_id = pagos_a_deal.get(pid)
            datos_deal = datos_deal_dict.get(deal_asociado_id, {}) if deal_asociado_id else {}
            
            pipeline_original_id = p.properties.get("hs_pipeline_stage", "")
            pipeline_traducido = mapeo_pipelines_dinamico.get(pipeline_original_id, pipeline_original_id)
            
            valor_original_metodo = p.properties.get(PROPIEDAD_METODO_PAGO, "")
            metodo_mapeado = mapeo_metodos.get(valor_original_metodo, valor_original_metodo)

            first_visit = contacto_info.get("hs_analytics_first_visit_timestamp")
            last_visit = contacto_info.get("hs_analytics_last_visit_timestamp")
            
            if first_visit:
                try: first_visit = datetime.fromtimestamp(int(first_visit)/1000).strftime('%Y-%m-%d %H:%M:%S')
                except: pass
            if last_visit:
                try: last_visit = datetime.fromtimestamp(int(last_visit)/1000).strftime('%Y-%m-%d %H:%M:%S')
                except: pass

            row = p.properties.copy()
            
            # --- NUEVAS VARIABLES DE RECENCIA PARA EL MODELO PREDICTIVO ---
            row["dias_desde_fecha_pago"] = calcular_dias(p.properties.get("fecha_de_pago"))
            row["dias_desde_creacion_pago"] = calcular_dias(p.properties.get("hs_createdate"))
            row["dias_desde_modificacion_pago"] = calcular_dias(p.properties.get("hs_lastmodifieddate"))
            row["dias_desde_close_date"] = calcular_dias(datos_deal.get("raw_close_date"))
            row["dias_desde_first_visit"] = calcular_dias(contacto_info.get("hs_analytics_first_visit_timestamp"))
            row["dias_desde_most_recent_visit"] = calcular_dias(contacto_info.get("hs_analytics_last_visit_timestamp"))
            # --------------------------------------------------------------

            row[PROPIEDAD_METODO_PAGO] = metodo_mapeado
            row["hs_pipeline_stage"] = pipeline_traducido
            
            row["Email"] = contacto_info.get("email", "Sin email")
            row["CL - CAPTOR"] = datos_deal.get("captor", "No asignado")
            row["Estado Cobro Deal"] = datos_deal.get("estado", "Sin estado")
            row["Close Date"] = datos_deal.get("close_date", "N/A")
            
            row["Site Visits"] = contacto_info.get("hs_analytics_num_visits", "0")
            row["Pages Viewed"] = contacto_info.get("hs_analytics_num_page_views", "0")
            row["First Visit"] = first_visit if first_visit else "N/A"
            row["Most Recent Visit"] = last_visit if last_visit else "N/A"
            
            row["Correos Enviados"] = contacto_info.get("hs_email_sended_count", "0")
            row["Correos Abiertos"] = contacto_info.get("hs_email_open_count", "0")
            row["Clicks en Correos"] = contacto_info.get("hs_email_click_count", "0")
            row["Correos Rebotados"] = contacto_info.get("hs_email_bounce_count", "0")
            
            data.append(row)
            
        print(f"Consolidación Final... Lote {i} procesado.")
        time.sleep(0.1)
    print("\n--- Consolidación finalizada ---\n")

    # 6. GUARDAR ARCHIVO
    if data:
        df_final = pd.DataFrame(data)
        nombre_archivo = "reporte_chile_completo_final.xlsx"
        df_final.to_excel(nombre_archivo, index=False)
        print(f"¡Proceso finalizado con éxito! Se generó '{nombre_archivo}'. Tiempo total: {int(time.time() - inicio_total)}s.")
        
        faltantes_captor = df_final[
            (df_final["CL - CAPTOR"] == "No asignado") | 
            (df_final["CL - CAPTOR"].isna()) | 
            (df_final["CL - CAPTOR"] == "")
        ].shape[0]
        
        print(f"\n[ANÁLISIS DE CONTROL TOTAL]")
        print(f"Total registros exportados: {df_final.shape[0]}")
        print(f"Registros sin captor asignado: {faltantes_captor}")
    else:
        print("No se encontraron datos de pagos para exportar.")

if __name__ == "__main__":
    generar_reporte_todo_chile(modo_prueba=MODO_PRUEBA)