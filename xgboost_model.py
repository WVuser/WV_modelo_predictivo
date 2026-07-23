import pandas as pd
import numpy as np
import time
from datetime import datetime
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, roc_auc_score, classification_report
from sklearn.preprocessing import LabelEncoder
import warnings
warnings.filterwarnings('ignore')

RUTA_ARCHIVO = "reporte_chile_completo v2.xlsx"
COLUMNA_TARGET = "hs_pipeline_stage"
ITERACIONES_XGB = 500

def mostrar_barra_avance(etapa, actual, total):
    porcentaje = (actual / total) * 100 if total > 0 else 0
    barra_largo = 30
    bloques = int(barra_largo * actual // total) if total > 0 else 0
    barra = "█" * bloques + "-" * (barra_largo - bloques)
    print(f"\r[{datetime.now().strftime('%H:%M:%S')}] {etapa}: |{barra}| {porcentaje:.1f}% ({actual}/{total})", end="", flush=True)

class BarraAvanceXGB(xgb.callback.TrainingCallback):
    def __init__(self, total_iteraciones):
        self.total_iteraciones = total_iteraciones

    def after_iteration(self, model, epoch, evals_log):
        mostrar_barra_avance("Entrenando XGBoost", epoch + 1, self.total_iteraciones)
        return False

def preparar_datos_y_entrenar():
    inicio_total = time.time()
    
    print("1. Iniciando carga de datos...")
    df = pd.read_excel(RUTA_ARCHIVO)
    df.columns = df.columns.str.strip()
    total_filas = len(df)
    print(f"\nDataset cargado correctamente. Filas totales: {total_filas}")

    mostrar_barra_avance("Preparando Target", 1, 4)
    df = df[df[COLUMNA_TARGET].isin(["Cobrado", "Rechazado"])]
    df['target'] = df[COLUMNA_TARGET].map({"Rechazado": 1, "Cobrado": 0})
    
    mostrar_barra_avance("Limpieza de Features", 2, 4)
    columnas_a_eliminar = [
        'Email', 'nombre_del_pago', 'fecha_de_pago', 'Close Date', 
        'First Visit', 'Most Recent Visit', COLUMNA_TARGET, 'Estado Cobro Deal',
        'hs_object_id', 'hs_createdate', 'hs_lastmodifieddate'
    ]
    columnas_existentes = [col for col in columnas_a_eliminar if col in df.columns]
    X = df.drop(columns=['target'] + columnas_existentes)
    y = df['target']

    for col in X.columns:
        if X[col].dtype == 'object':
            X[col] = X[col].fillna("Desconocido")
        else:
            X[col] = X[col].fillna(0)

    mostrar_barra_avance("Codificación Categórica", 3, 4)
    label_encoders = {}
    for col in X.select_dtypes(include=['object']).columns:
        le = LabelEncoder()
        X[col] = X[col].astype(str)
        X[col] = le.fit_transform(X[col])
        label_encoders[col] = le

    mostrar_barra_avance("División Train/Test", 4, 4)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.20, random_state=42, stratify=y)
    print("\n\n--- Preprocesamiento Finalizado ---")
    print(f"Set de Entrenamiento: {X_train.shape[0]} filas | Set de Prueba: {X_test.shape[0]} filas")

    print("\n2. Iniciando entrenamiento del modelo XGBoost...")
    
    modelo_xgb = xgb.XGBClassifier(
        n_estimators=ITERACIONES_XGB,
        learning_rate=0.05,
        max_depth=6,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        tree_method='hist',
        callbacks=[BarraAvanceXGB(ITERACIONES_XGB)]
    )

    modelo_xgb.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False
    )
    
    print("\n\n--- Entrenamiento Finalizado ---")

    print("3. Generando métricas de evaluación...")
    predicciones = modelo_xgb.predict(X_test)
    probabilidades = modelo_xgb.predict_proba(X_test)[:, 1]

    auc_roc = roc_auc_score(y_test, probabilidades)
    accuracy = accuracy_score(y_test, predicciones)

    print("\n=== REPORTE DE DESEMPEÑO DEL MODELO ===")
    print(f"Exactitud (Accuracy): {accuracy:.4f}")
    print(f"Área bajo la curva (AUC-ROC): {auc_roc:.4f}")
    print("\nReporte Detallado:")
    print(classification_report(y_test, predicciones, target_names=["0 (Cobrado/Retenido)", "1 (Rechazado/Churn)"]))
    
    importancia = pd.DataFrame({
        'Variable': X.columns,
        'Importancia': modelo_xgb.feature_importances_
    }).sort_values(by='Importancia', ascending=False)
    
    print("\nTop 5 Variables más importantes para predecir el Churn:")
    print(importancia.head(5).to_string(index=False))

    print(f"\n¡Proceso finalizado! Tiempo total de ejecución: {int(time.time() - inicio_total)}s.")

if __name__ == "__main__":
    preparar_datos_y_entrenar()