"""
feature extraction
"""

# from standard library
import sys
import os
import glob
from datetime import datetime

# from dependencies
import numpy as np
from sklearn.externals import joblib

# from hvc
from .parseconfig import parse_config
from . import features

SELECT_TEMPLATE = """select:
  global:
    num_replicates: None
    num_train_samples:
      start : None
      stop : None
      step : None
    num_test_samples: None

    models:"""

MODELS_TEMPLATE = """
    -
      model: {0}
      feature_list_indices: {1}
      hyperparameters:
        {2}
"""

SVM_HYPERPARAMS = """C : None
        gamma : None
"""

KNN_HYPERPARAMS = """k : None
"""

TODO_TEMPLATE = """  todo_list:
    -
      feature_file : {0}
      output_dir: {1}"""

def dump_select_config(summary_ftr_file_dict,
                       timestamp,
                       summary_filename,
                       output_dir):
    """dumps summary output dict from extract to a config file for select
    
    Parameters
    ----------
    summary_ftr_file_dict : dictionary
        as defined in featureextract.extract
    timestamp : string
        time stamp from feature files, added to select config filename
    summary_filename : string
        name of summary feature file
    output_dir : string
        name of output directory -- assumes it will be the same as it was for extract.yml

    Returns
    -------
    None
    
    Doesn't return anything, just saves .yml file
    """

    select_config_filename = 'select.config.from_extract_output_' + timestamp + '.yml'
    with open(select_config_filename, 'w') as yml_outfile:
        yml_outfile.write(SELECT_TEMPLATE)
        for model_name, model_ID in summary_ftr_file_dict['feature_list_group_ID_dict'].items():
            inds = np.flatnonzero(summary_ftr_file_dict['feature_list_group_ID']==model_ID).tolist()
            inds = ', '.join(str(ind) for ind in inds)
            if model_name == 'svm':
                hyperparams = SVM_HYPERPARAMS
            elif model_name == 'knn':
                hyperparams = KNN_HYPERPARAMS
            yml_outfile.write(MODELS_TEMPLATE.format(model_name,
                                                     inds,
                                                     hyperparams))
        yml_outfile.write(TODO_TEMPLATE.format(summary_filename,
                                               output_dir))

def extract(config_file):
    """main function that runs feature extraction.
    Does not return anything, just runs through directories specified in config_file
    and extracts features.
    
    Parameters
    ----------
    config_file : string
        filename of YAML file that configures feature extraction    
    """
    extract_config = parse_config(config_file,'extract')
    print('Parsed extract config.')

    home_dir = os.getcwd()

    todo_list = extract_config['todo_list']
    for ind, todo in enumerate(todo_list):

        timestamp = datetime.now().strftime('%y%m%d_%H%M')

        print('Completing item {} of {} in to-do list'.format(ind+1,len(todo_list)))
        file_format = todo['file_format']
        if file_format == 'evtaf':
            if 'evfuncs' not in sys.modules:
                from . import evfuncs
        elif file_format == 'koumura':
            if 'koumura' not in sys.modules:
                from . import koumura

        feature_list = todo['feature_list']

        output_dir = todo['output_dir'] + 'extract_output_' + timestamp
        if not os.path.isdir(output_dir):
            os.mkdir(output_dir)

        data_dirs = todo['data_dirs']
        for data_dir in data_dirs:
            print('Changing to data directory: {}'.format(data_dir))
            os.chdir(data_dir)

            if 'features_from_all_files' in locals():
                # from last time through loop
                # (need to re-initialize for each directory)
                del features_from_all_files

            if file_format == 'evtaf':
                songfiles_list = glob.glob('*.cbin')
            elif file_format == 'koumura':
                songfiles_list = glob.glob('*.wav')

            num_songfiles = len(songfiles_list)
            all_labels = []
            song_IDs = []
            song_ID_counter = 0
            for file_num, songfile in enumerate(songfiles_list):
                print('Processing audio file {} of {}.'.format(file_num + 1, num_songfiles))
                ftrs_from_curr_file, labels, ftr_inds = features.extract.from_file(songfile,
                                                                                   todo['file_format'],
                                                                                   todo['feature_list'],
                                                                                   extract_config['spect_params'],
                                                                                   todo['labelset'],
                                                                                   extract_config['segment_params'])
                if all([returned is None for returned in (ftrs_from_curr_file,
                                                          labels,
                                                          ftr_inds)]):
                    continue
                all_labels.extend(labels)
                song_IDs.extend([song_ID_counter] * len(labels))
                song_ID_counter += 1

                if 'features_from_all_files' in locals():
                    features_from_all_files = np.concatenate((features_from_all_files,
                                                              ftrs_from_curr_file),
                                                             axis=0)
                else:
                    features_from_all_files = ftrs_from_curr_file

            # get dir name without the rest of path so it doesn't have separators in the name
            # because those can't be in filename
            just_dir_name = os.getcwd().split(os.path.sep)[-1]
            feature_file = os.path.join(output_dir,
                                           'features_from_' + just_dir_name + '_created_' + timestamp)
            feature_file_dict = {
                'labels' : all_labels,
                'feature_list': todo['feature_list'],
                'spect_params' : extract_config['spect_params'],
                'labelset' : todo['labelset'],
                'file_format' : todo['file_format'],
                'bird_ID' : todo['bird_ID'],
                'song_IDs' : song_IDs,
                'features' : features_from_all_files,
                'features_arr_column_IDs' : ftr_inds
                                }
            if 'feature_list_group_ID' in todo:
                feature_file_dict['feature_list_group_ID'] = todo['feature_list_group_ID']
                feature_file_dict['feature_list_group_ID_dict'] = todo['feature_list_group_ID_dict']

            joblib.dump(feature_file_dict,
                        feature_file,
                        compress=3)

        ##########################################################
        # after looping through all data_dirs for this todo_item #
        ##########################################################
        print('making summary file')
        os.chdir(output_dir)
        summary_filename = os.path.join(output_dir, 'summary_feature_file_created_' + timestamp)
        ftr_output_files = glob.glob('*features_from_*')
        if len(ftr_output_files) > 1:
            #make a 'summary' data file
            list_of_output_dicts = []
            summary_ftr_file_dict = {}
            for feature_file in ftr_output_files:
                feature_file_dict = joblib.load(feature_file)

                if 'features' not in summary_ftr_file_dict:
                    summary_ftr_file_dict['features'] = feature_file_dict['features']
                else:
                    summary_ftr_file_dict['features'] = np.concatenate((summary_ftr_file_dict['features'],
                                                                         feature_file_dict['features']))
                if 'labels' not in summary_ftr_file_dict:
                    summary_ftr_file_dict['labels'] = feature_file_dict['labels']
                else:
                    summary_ftr_file_dict['labels'] = summary_ftr_file_dict['labels'] + feature_file_dict['labels']

                if 'spect_params' not in summary_ftr_file_dict:
                    summary_ftr_file_dict['spect_params'] = feature_file_dict['spect_params']
                else:
                    if feature_file_dict['spect_params'] != summary_ftr_file_dict['spect_params']:
                        raise ValueError('mismatch between spect_params in {} '
                                         'and other feature files'.format(feature_file))

                if 'labelset' not in summary_ftr_file_dict:
                    summary_ftr_file_dict['labelset'] = feature_file_dict['labelset']
                else:
                    if feature_file_dict['labelset'] != summary_ftr_file_dict['labelset']:
                        raise ValueError('mismatch between labelset in {} '
                                         'and other feature files'.format(feature_file))

                if 'file_format' not in summary_ftr_file_dict:
                    summary_ftr_file_dict['file_format'] = feature_file_dict['file_format']
                else:
                    if feature_file_dict['file_format'] != summary_ftr_file_dict['file_format']:
                        raise ValueError('mismatch between file_format in {} '
                                         'and other feature files'.format(feature_file))

                if 'bird_ID' not in summary_ftr_file_dict:
                    summary_ftr_file_dict['bird_ID'] = feature_file_dict['bird_ID']
                else:
                    if feature_file_dict['bird_ID'] != summary_ftr_file_dict['bird_ID']:
                        raise ValueError('mismatch between bird_ID in {} '
                                         'and other feature files'.format(feature_file))

                if 'song_IDs' not in summary_ftr_file_dict:
                    summary_ftr_file_dict['song_IDs'] = feature_file_dict['song_IDs']
                else:
                    curr_last_ID = summary_ftr_file_dict['song_IDs'][-1]
                    tmp_song_IDs = [el + curr_last_ID + 1 for el in feature_file_dict['song_IDs']]
                    summary_ftr_file_dict['song_IDs'].extend(tmp_song_IDs)

                if 'feature_list' not in summary_ftr_file_dict:
                    summary_ftr_file_dict['feature_list'] = feature_file_dict['feature_list']
                else:
                    if feature_file_dict['feature_list'] != summary_ftr_file_dict['feature_list']:
                        raise ValueError('mismatch between feature_list in {} '
                                         'and other feature files'.format(feature_file))

                if 'feature_list_group_ID' not in summary_ftr_file_dict:
                    summary_ftr_file_dict['feature_list_group_ID'] = feature_file_dict['feature_list_group_ID']
                else:
                    if any(feature_file_dict['feature_list_group_ID'] !=
                                   summary_ftr_file_dict['feature_list_group_ID']):
                        raise ValueError('mismatch between feature_list_group_ID in {} '
                                         'and other feature files'.format(feature_file))

                if 'feature_list_group_ID_dict' not in summary_ftr_file_dict:
                    summary_ftr_file_dict['feature_list_group_ID_dict'] = \
                        feature_file_dict['feature_list_group_ID_dict']
                else:
                    if feature_file_dict['feature_list_group_ID_dict'] != \
                            summary_ftr_file_dict['feature_list_group_ID_dict']:
                        raise ValueError('mismatch between feature_list_group_ID_dict in {} '
                                         'and other feature files'.format(feature_file))

                if 'features_arr_column_IDs' not in summary_ftr_file_dict:
                    summary_ftr_file_dict['features_arr_column_IDs'] = feature_file_dict['features_arr_column_IDs']
                else:
                    if any(feature_file_dict['features_arr_column_IDs'] !=
                                   summary_ftr_file_dict['features_arr_column_IDs']):
                        raise ValueError('mismatch between features_arr_column_IDs in {} '
                                         'and other feature files'.format(feature_file))

            joblib.dump(summary_ftr_file_dict,
                        summary_filename)
        else:  # if only one feature_file
            os.rename(ftr_output_files[0],
                      summary_filename)
            summary_ftr_file_dict = joblib.load(summary_filename)
        dump_select_config(summary_ftr_file_dict,
                           timestamp,
                           summary_filename,
                           todo['output_dir'])
    os.chdir(home_dir)
