"""
Espejo manual de `maize-doctor-classifier/config/dataset.yaml -> dataset.classes`.

No hay forma de importar ese archivo desde este repo (proyecto Python distinto, sin
paquete compartido), asi que esta lista se mantiene sincronizada a mano. El orden aqui
no importa - a diferencia del pipeline de ML, esta API nunca indexa por posicion, solo
valida pertenencia al conjunto - pero los strings deben coincidir exactamente.
"""

DIAGNOSIS_LABELS: tuple[str, ...] = (
    "common_rust",
    "fall_armyworm",
    "gray_leaf_spot",
    "healthy",
    "lethal_necrosis",
    "nitrogen_deficiency",
    "northern_corn_leaf_blight",
    "phosphorus_deficiency",
    "potassium_deficiency",
)
