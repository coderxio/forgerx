MEPS_CONFIG = {
    "age": ["0-3", "4-7", "8-11", "12-18", "19-49", "50-64", "65-99"],
    "demographic_distribution_flags": {"age": "Y", "gender": "Y", "state": "Y"},
    "meps_year": "18",
    "module_name": "Module Name", # required (text)
    "assign_to_attribute": "", # optional (text) default is <<module_name>>_prescription
    "as_needed": None, # optional (boolean)
    "chronic": None, # optional (boolean)
    "refills": 0, # optional (numeric) default is 0
    "state_prefix": "Prescribe_",
    "ingredient_distribution_suffix": "_ingredient_distribution",
    "product_distribution_suffix": "_product_distribution",
    "distribution_file_type": "csv",
    "rxclass_include": [
        {
            "class_id": "R01AD",
            "relationship": "ATC"
        }
    ],
    "rxclass_exclude": [],
    "rxcui_include": ["435"],
    "rxcui_exclude": [],
    "ingredient_tty_filter": "IN",
    "dfg_df_filter": [
        "Dry Powder Inhaler",
        "Inhalation Powder",
        "Inhalation Solution",
        "Metered Dose Inhaler"
    ]
}
