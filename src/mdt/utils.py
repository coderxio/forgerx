import json
import re
import pandas as pd
from mdt.config import MEPS_CONFIG
from mdt.database import db_query
from mdt import meps


def read_json(file_name):
    # Opening JSON file
    f = open(file_name,)

    # returns JSON object as a dictionary
    data = json.load(f)
    return data


# Monkey patched this function to get run_mdt working by removing the filename arg and importing from config
def age_values():
    """reads age_ranges from JSON to create dataframe with age_values"""

    data = {}
    data['age'] = MEPS_CONFIG['age']
    data['age_values'] = [list(range(int(age.split('-')[0]), int(age.split('-')[1])+1)) for age in data['age']]
    df = pd.DataFrame(data)
    df = df.explode('age_values')
    return df


# TODO: Add option to string search doseage form
def rxcui_ndc_matcher(rxcui_list):
    """mashes list of RxCUIs against RxNorm combined table to get matching NDCs. 
    Select output of return, clipboard, csv....return is default"""

    df = db_query('SELECT * FROM rxcui_ndc')
    filtered_df = df[df['medication_ingredient_rxcui'].isin(rxcui_list) | df['medication_product_rxcui'].isin(rxcui_list)]

    print("RXCUI list matched on {0} NDCs".format(filtered_df['medication_ndc'].count()))

    return filtered_df


def get_prescription_details(rxcui):
    """mashes a medication product RXCUI against MEPS prescription details + RxNorm to get common prescription details.
    Either outputs False or a prescription object
    https://github.com/synthetichealth/synthea/wiki/Generic-Module-Framework%3A-States#medicationorder"""

    df = db_query('SELECT * FROM meps_rx_qty_ds')
    filtered_df = df[df['medication_product_rxcui'] == rxcui]

    # If the medication product does not have any reliable prescription details, don't generate prescription details
    # NOTE: not sure if 'return False' is the best way to do this - open to alternatives
    if len(filtered_df.index) == 0:
        return False

    # Currently, this just picks the most common prescription details at the medication product level
    # TODO: if there are more than 1 common prescription details, randomly pick one - favoring the more common ones
    selected_rx_details = filtered_df.iloc[0].to_dict()

    # NOTE: Synthea currently doesn't appear to have a field to capture quantity prescribed as part of the MedicationOrder
    rx_qty = int(selected_rx_details['RXQUANTY'])
    rx_ds = int(selected_rx_details['RXDAYSUP'])

    # TODO: maybe do this in the filtered_df step above?
    if rx_qty == 0 or rx_ds == 0:
        return False

    # See FHIR Timing reference for how these variables are calculated
    # http://hl7.org/fhir/DSTU2/datatypes.html#Timing
    frequency = int(rx_qty / rx_ds) if rx_qty >= rx_ds else 1
    period = int(rx_ds / rx_qty) if rx_ds > rx_qty else 1

    dosage = {
        'amount': 1,
        'frequency': frequency,
        'period': period,
        'unit': 'days'
    }

    duration = {
        'quantity': rx_ds,
        'unit': 'days'
    }

    prescription = {
        'dosage': dosage,
        'duration': duration
    }

    return prescription


def filter_by_df(rxcui_ndc_df, dfg_df_list, method='include'):
    """Gets DFs from dfg_df table that match either a DF in the list, or have a DFG that matches a DFG in the list
    If dfg_df list is empty, return the rxcui_ndc_df without filtering
    Select method option of include or exclude....include is default"""

    if len(dfg_df_list) == 0:
        return rxcui_ndc_df

    dfg_df_df = db_query('SELECT * FROM dfg_df')
    filtered_dfg_df_df = dfg_df_df[dfg_df_df['dfg'].isin(dfg_df_list) | dfg_df_df['df'].isin(dfg_df_list)]
    df_list = filtered_dfg_df_df['df'].tolist()

    if method == 'include':
        filtered_rxcui_ndc_df = rxcui_ndc_df[rxcui_ndc_df['dose_form_name'].isin(df_list)]
    elif method == 'exclude':
        filtered_rxcui_ndc_df = rxcui_ndc_df[~rxcui_ndc_df['dose_form_name'].isin(df_list)]
    else:
        filtered_rxcui_ndc_df = rxcui_ndc_df

    print("RXCUI list filtered on DF matched on {0} NDCs".format(filtered_rxcui_ndc_df['medication_ndc'].count()))

    return filtered_rxcui_ndc_df


def output_df(df,output='csv', filename='df_output'):
    """Outputs a dataframe to a csv of clipboard if you use the output=clipboard arguement"""

    if output == 'clipboard':
        df.to_clipboard(index=False, excel=True)
    elif output == 'csv':
        df.to_csv('data/'+filename+'.csv', index=False)


def output_json(data, filename='json_output'):
    with open('data/'+filename+'.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def normalize_name(name, case='camel'):
    """ Case is optional and choices are lower, upper, and camel """

    #Replace all non-alphanumeric characters with an underscore
    name = re.sub(r"[^a-zA-Z0-9]", "_", name)
    # Then, replace all duplicate underscores with just one underscore
    name = re.sub(r"_{2,}", "_", name)
    # If there'a an underscore at the end of the word, remove
    name = re.sub(r"_$", "", name)

    if case == 'lower':
        name = name.lower()
    elif case == 'upper':
        name = name.upper()
    elif case == 'camel':
        name = name.title()

    return name


def get_meps_rxcui_ndc_df(rxcui_ndc_df):
    #Read in MEPS Reference table
    meps_reference = db_query(meps.utils.get_sql('meps_reference.sql'))

    #Join MEPS to filtered rxcui_ndc dataframe (rxcui_list)
    meps_rxcui_ndc_df = meps_reference.astype(str).merge(rxcui_ndc_df.astype(str)[['medication_ingredient_name', 'medication_ingredient_rxcui','medication_product_name', 'medication_product_rxcui', 'medication_ndc']], how = 'inner', left_on = 'RXNDC', right_on = 'medication_ndc')
    
    output_df(meps_rxcui_ndc_df, filename='meps_rxcui_ndc_df_output')

    return meps_rxcui_ndc_df

def generate_module_json(meps_rxcui_ndc_df):
    config = MEPS_CONFIG
    module_name = config['module_name']
    demographic_distribution_flags = config['demographic_distribution_flags']
    state_prefix = config['state_prefix']
    ingredient_distribution_suffix = config['ingredient_distribution_suffix']
    product_distribution_suffix = config['product_distribution_suffix']
    as_needed = config['as_needed']
    chronic = config['chronic']
    refills = config['refills']

    assign_to_attribute = normalize_name(module_name + '_prescription', case = 'lower') if config['assign_to_attribute'] == '' else normalize_name(config['assign_to_attribute'], 'lower')
    reason = assign_to_attribute

    module_dict = {}

    module_dict['name'] = module_name + ' Medications'
    module_dict['remarks'] = [
        'This submodule prescribes a medication based on distributions of',
        '<<INPUTS FROM CONFIG>>.', # i.e. age, gender, state
        '',
        'IT IS UP TO THE CALLING MODULE TO END THIS MEDICATION BY ATTRIBUTE.',
        'All medications prescribed in this module are assigned to the attribute',
        '\'' + assign_to_attribute + '\'.',
        '',
        'Input query for this submodule:',
        '  Include: ',
        '    RxClass: <<RXCLASS INCLUDES>>',
        '    RxNorm: <<RXCUI INCLUDES>>',
        '  Exclude:',
        '    RxClass: <<RXCLASS EXCLUDES>>',
        '    RxNorm: <<RXCUI EXCLUDES>>',
        '',
        'Reference links:',
        '  RxClass: https://mor.nlm.nih.gov/RxClass/',
        '  RxNorm: https://www.nlm.nih.gov/research/umls/rxnorm/index.html',
        '  RxNav: https://mor.nlm.nih.gov/RxNav/',
        '  MEPS: https://meps.ahrq.gov/mepsweb/data_stats/MEPS_topics.jsp?topicid=46Z-1',
        '  FDA: https://www.fda.gov/drugs/drug-approvals-and-databases/national-drug-code-directory',
        '',
        'Made with (</>) by the CodeRx Medication Diversification Tool'
    ]
    # NOTE: not sure the difference between 1 and 2... I think 2 is the most recent version(?)
    module_dict['gmf_version'] = 2

    states_dict = {}

    # Initial state (required)
    # NOTE: if we change to conditional to check for existence of medication, channge direct_transition to transition
    states_dict['Initial'] = {
        'type': 'Initial',
        'conditional_transition': [
            {
                'condition': {
                    'condition_type': 'Attribute',
                    'attribute': assign_to_attribute,
                    'operator': 'is nil'
                },
                'transition': normalize_name(state_prefix + 'Ingredient')
            },
            {
                'transition': 'Terminal'
            }
        ]
    }

    # Terminal state (required)
    states_dict['Terminal'] = {
        'type': 'Terminal'
    }

    # Generate ingredient table transition
    ingredient_transition_state_remarks = [
        '======================================================================',
        ' MEDICATION INGREDIENT TABLE TRANSITION                               ',
        '======================================================================',
    ]
    ingredient_transition_state_remarks.append('Ingredients in lookup table:')
    medication_ingredient_name_list = meps_rxcui_ndc_df['medication_ingredient_name'].unique().tolist()
    for idx, name in enumerate(medication_ingredient_name_list, start=1):
        ingredient_detail = ' {0}. {1}'.format(idx, name)
        ingredient_transition_state_remarks.append(ingredient_detail)

    medication_ingredient_transition_name_list = meps_rxcui_ndc_df['medication_ingredient_name'].apply(lambda x: normalize_name(state_prefix + x)).unique().tolist()
    filename = module_name + ingredient_distribution_suffix
    lookup_table_name = filename + '.csv'
    lookup_table_transition = []
    for idx, transition in enumerate(medication_ingredient_transition_name_list):
        lookup_table_transition.append({
            'transition': transition,
            'default_probability': '1' if idx == 0 else '0',
            'lookup_table_name': lookup_table_name
        })
    state_name = normalize_name(state_prefix + 'Ingredient')
    states_dict[state_name] = {
        'name': state_name,
        'remarks': ingredient_transition_state_remarks,
        'type': 'Simple',
        'lookup_table_transition': lookup_table_transition
    }

    # Generate product table transition
    medication_ingredient_name_list = meps_rxcui_ndc_df['medication_ingredient_name'].unique().tolist()
    for ingredient_name in medication_ingredient_name_list:
        product_transition_state_remarks = [
            '======================================================================',
            ' ' + ingredient_name.upper() + ' MEDICATION PRODUCT TABLE TRANSITION  ',
            '======================================================================',
        ]
        filename = module_name + '_' + ingredient_name + product_distribution_suffix
        lookup_table_name = filename + '.csv'
        lookup_table_transition = []

        product_transition_state_remarks.append('Products in lookup table:')
        medication_product_name_list = meps_rxcui_ndc_df[meps_rxcui_ndc_df['medication_ingredient_name']==ingredient_name]['medication_product_name'].unique().tolist()
        for idx, name in enumerate(medication_product_name_list, start=1):
            product_detail = ' {0}. {1}'.format(idx, name)
            product_transition_state_remarks.append(product_detail)

        medication_product_transition_name_list = meps_rxcui_ndc_df[meps_rxcui_ndc_df['medication_ingredient_name']==ingredient_name]['medication_product_name'].apply(lambda x: normalize_name(state_prefix + x)).unique().tolist()
        for idx, transition in enumerate(medication_product_transition_name_list):
            lookup_table_transition.append({
                'transition': transition,
                'default_probability': '1' if idx == 0 else '0',
                'lookup_table_name': lookup_table_name
            })
        state_name = normalize_name(state_prefix + ingredient_name)
        states_dict[state_name] = {
            'name': state_name,
            'remarks': product_transition_state_remarks,
            'type': 'Simple',
            'lookup_table_transition': lookup_table_transition
        }

    # Generate MedicationOrder states
    # medication_products = list(meps_rxcui_ndc_df[['medication_product_name', 'medication_product_rxcui']].to_records(index=False))
    medication_products_df = meps_rxcui_ndc_df.groupby(['medication_product_name', 'medication_product_rxcui']).size().reset_index(name='count')
    medication_products_list = medication_products_df[['medication_product_name', 'medication_product_rxcui']].values.tolist()
    #medication_products = list(medication_products_df[['medication_product_name', 'medication_product_rxcui']].to_records(index=False))

    medication_order_state_remarks = [
        '======================================================================',
        ' BEGIN MEDICATION ORDER STATES                                        ',
        '======================================================================',
    ]
    for idx, (medication_product_name, medication_product_rxcui) in enumerate(medication_products_list):
        state_name = normalize_name(state_prefix + medication_product_name)
        refills = refills if isinstance(refills, int) else 0
        codes = {
            'system': 'RxNorm',
            'code': medication_product_rxcui,
            'display': medication_product_name
        }
        prescription = {
            'refills': refills
        }
        if as_needed in (True, False):
            prescription['as_needed'] = as_needed
        states_dict[state_name] = {
            'name': state_name,
            'type': 'MedicationOrder',
            'assign_to_attribute': assign_to_attribute,
            'reason': reason,
            'codes': [ codes ],
            'prescription': prescription,
            'direct_transition': 'Terminal'
        }
        if chronic in (True, False):
            states_dict[state_name]['chronic'] = chronic

        if idx == 0:
            medication_order_state_remarks_dict = {'remarks': medication_order_state_remarks}
            states_dict[state_name] = {**medication_order_state_remarks_dict, **states_dict[state_name]}

        prescription_details = get_prescription_details(medication_product_rxcui)
        if prescription_details:
            states_dict[state_name]['prescription'] = {**states_dict[state_name]['prescription'], **prescription_details}

    module_dict['states'] = states_dict
    
    filename = normalize_name(module_name + '_medication', 'lower')
    output_json(module_dict, filename=filename)


def generate_module_csv(meps_rxcui_ndc_df):
    meps_rxcui = meps_rxcui_ndc_df
    # Optional: Age range join - can be customized in the mdt_config.json file
    # groupby_demographic_variable: must be either an empty list [] or list of patient demographics (e.g., age, gender, state) - based on user inputs in the mdt_config.json file

    config = MEPS_CONFIG
    module_name = config['module_name']
    demographic_distribution_flags = config['demographic_distribution_flags']
    state_prefix = config['state_prefix']
    ingredient_distribution_suffix = config['ingredient_distribution_suffix']
    product_distribution_suffix = config['product_distribution_suffix']

    groupby_demographic_variables = []
    for k, v in demographic_distribution_flags.items():
        if v == 'Y':
               groupby_demographic_variables.append(k)  
        
    # Optional: age range from MEPS 
    if demographic_distribution_flags['age'] == 'Y':
        age_ranges = age_values()
        meps_rxcui_ndc_df = meps_rxcui_ndc_df.merge(age_ranges.astype(str), how='inner', left_on='AGELAST', right_on='age_values')
    
    # Optional: state-region mapping from MEPS 
    if demographic_distribution_flags['state'] == 'Y':
        meps_rxcui_ndc_df = meps_rxcui_ndc_df.merge(meps.columns.meps_region_states.astype(str), how='inner', left_on='region_num', right_on='region_value')

    # Clean text to JSON/SQL-friendly format 
    for col in meps_rxcui_ndc_df[['medication_ingredient_name', 'medication_product_name']]:
        meps_rxcui_ndc_df[col] = meps_rxcui_ndc_df[col].apply(lambda x: normalize_name(x))
        
    dcp_dict = {}
    medication_ingredient_list = meps_rxcui_ndc_df['medication_ingredient_name'].unique().tolist()
  
    # Ingredient Name Distribution (Transition 1)
    """Numerator = ingredient_name
    Denominator = total population [filtered by rxclass_name upstream between rxcui_ndc & rxclass]
    1. Find distinct count of patients (DUPERSID) = patient_count
    2. Multiply count of patients * personweight = weighted_patient_count
    3. Add the weighted_patient_counts, segmented by ingredient_name + selected patient demographics = patients_by_demographics (Numerator) 
    4. Add the patients_by_demographics from Step 3 = weighted_patient_count_total (Denominator) -- Taking SUM of SUMs to make the Denominator = 100%  
    5. Calculate percentage (Output from Step 3/Output from Step 4) -- format as 0.0-1.0 per Synthea requirements. 
    6. Add the 'prescribe_' prefix to the medication_ingredient_name (e.g., 'prescribe_fluticasone') 
    7. Pivot the dataframe to transpose medication_ingredient_names from rows to columns """

    filename = normalize_name(module_name + ingredient_distribution_suffix, 'lower')
    # 1
    dcp_dict['patient_count_ingredient'] = meps_rxcui_ndc_df[['medication_ingredient_name',  'medication_ingredient_rxcui', 'person_weight', 'DUPERSID']+groupby_demographic_variables].groupby(['medication_ingredient_name',  'medication_ingredient_rxcui', 'person_weight']+groupby_demographic_variables)['DUPERSID'].nunique()
    dcp_df = pd.DataFrame(dcp_dict['patient_count_ingredient']).reset_index()
    # 2
    dcp_df['weighted_patient_count_ingredient'] = dcp_df['person_weight'].astype(float)*dcp_df['DUPERSID']
    # 3
    dcp_dict['patients_by_demographics_ingredient'] = dcp_df.groupby(['medication_ingredient_name']+groupby_demographic_variables)['weighted_patient_count_ingredient'].sum()
    dcp_demographic_df = pd.DataFrame(dcp_dict['patients_by_demographics_ingredient']).reset_index()
    # 4
    if len(groupby_demographic_variables) > 0:
        dcp_demographictotal_df = pd.merge(dcp_demographic_df,  dcp_demographic_df.groupby(groupby_demographic_variables)['weighted_patient_count_ingredient'].sum(), how = 'inner', left_on = groupby_demographic_variables, right_index=True, suffixes = ('_demographic', '_total'))
    else:
        dcp_demographictotal_df = dcp_demographic_df
        dcp_demographictotal_df['weighted_patient_count_ingredient_demographic'] = dcp_demographic_df['weighted_patient_count_ingredient']
        dcp_demographictotal_df['weighted_patient_count_ingredient_total'] = dcp_demographic_df['weighted_patient_count_ingredient'].sum()
    # 5
    dcp_demographictotal_df['percent_ingredient_patients'] = round(dcp_demographictotal_df['weighted_patient_count_ingredient_demographic']/dcp_demographictotal_df['weighted_patient_count_ingredient_total'], 3)
    # 6 TODO: change this column to medication_product_state_name(?)
    dcp_demographictotal_df['medication_ingredient_transition_name'] = dcp_demographictotal_df['medication_ingredient_name'].apply(lambda x: normalize_name(state_prefix + x))
    # 7
    dcp_dict['percent_ingredient_patients'] = dcp_demographictotal_df
    if len(groupby_demographic_variables) > 0:
        dcp_dict['percent_ingredient_patients'] = dcp_dict['percent_ingredient_patients'].reset_index().pivot(index=groupby_demographic_variables, columns='medication_ingredient_transition_name', values='percent_ingredient_patients').reset_index()
    else:
        dcp_dict['percent_ingredient_patients'] = dcp_dict['percent_ingredient_patients'][['medication_ingredient_transition_name', 'percent_ingredient_patients']].set_index('medication_ingredient_transition_name').T
        
    # Fill NULLs and save as CSV
    dcp_dict['percent_ingredient_patients'].fillna(0, inplace=True)
    ingredient_distribution_df = dcp_dict['percent_ingredient_patients']
    output_df(ingredient_distribution_df, output='csv', filename=filename)

    # Product Name Distribution (Transition 2)
    """Numerator = product_name 
    Denominator = ingredient_name
    Loop through all the ingredient_names to create product distributions by ingredient name
    Same steps as above for Ingredient Name Distribution (1-7), but first filter medication_product_names for only those that have the same medication_ingredient_name (Step 0) """


    for ingredient_name in medication_ingredient_list:
        filename = normalize_name(module_name + '_' + ingredient_name + product_distribution_suffix, 'lower')
        # 0
        meps_rxcui_ingred = meps_rxcui_ndc_df[meps_rxcui_ndc_df['medication_ingredient_name']==ingredient_name][['medication_product_name',  'medication_product_rxcui', 'medication_ingredient_name', 'medication_ingredient_rxcui', 'person_weight', 'DUPERSID']+groupby_demographic_variables]
        # 1
        dcp_dict['patient_count_product'] = meps_rxcui_ingred.groupby(['medication_product_name',  'medication_product_rxcui',  'medication_ingredient_name',  'medication_ingredient_rxcui', 'person_weight']+groupby_demographic_variables)['DUPERSID'].nunique()
        dcp_df = pd.DataFrame(dcp_dict['patient_count_product']).reset_index()
        # 2
        dcp_df['weighted_patient_count_product'] = dcp_df['person_weight'].astype(float)*dcp_df['DUPERSID']
        # 3
        dcp_dict['patients_by_demographics_product'] = dcp_df.groupby(['medication_product_name', 'medication_ingredient_name']+groupby_demographic_variables)['weighted_patient_count_product'].sum()
        dcp_demographic_df = pd.DataFrame(dcp_dict['patients_by_demographics_product']).reset_index()
        # 4
        dcp_demographictotal_df = pd.merge(dcp_demographic_df,  dcp_demographic_df.groupby(['medication_ingredient_name']+groupby_demographic_variables)['weighted_patient_count_product'].sum(), how = 'inner', left_on = ['medication_ingredient_name']+groupby_demographic_variables, right_index=True, suffixes = ('_demographic', '_total'))
        # 5
        dcp_demographictotal_df['percent_product_patients'] = round(dcp_demographictotal_df['weighted_patient_count_product_demographic']/dcp_demographictotal_df['weighted_patient_count_product_total'], 3)
        # 6 TODO: change this column to medication_product_state_name or medication_product_transition_name(?)
        dcp_demographictotal_df['medication_product_transition_name'] = dcp_demographictotal_df['medication_product_name'].apply(lambda x: normalize_name(state_prefix + x))
        # 7
        dcp_dict['percent_product_patients'] = dcp_demographictotal_df
        if len(groupby_demographic_variables) > 0:
            dcp_dict['percent_product_patients'] = dcp_dict['percent_product_patients'].reset_index().pivot(index= groupby_demographic_variables, columns = 'medication_product_transition_name', values='percent_product_patients').reset_index()
        else:
            dcp_dict['percent_product_patients'] = dcp_dict['percent_product_patients'][['medication_product_transition_name', 'percent_product_patients']].set_index('medication_product_transition_name').T
        
        # Fill NULLs and save as CSV 
        dcp_dict['percent_product_patients'].fillna(0, inplace=True)
        product_distribution_df = dcp_dict['percent_product_patients']
        output_df(product_distribution_df, output='csv', filename=filename)

    return dcp_dict