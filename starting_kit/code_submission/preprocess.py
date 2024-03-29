import datetime
import pandas as pd
import numpy as np
from multiprocessing import Pool

import CONSTANT
from util import log, timeit


uni_ops = {
    CONSTANT.TIME_PREFIX: {
        'week': lambda df: df.dt.week,
        'year': lambda df: df.dt.year,
        'month': lambda df: df.dt.month,
        'day': lambda df: df.dt.day,
        'hour': lambda df: df.dt.hour,
        # 'minute': lambda df: df.dt.minute,
        'dayofweek': lambda df: df.dt.dayofweek,
        'dayofyear': lambda df: df.dt.dayofyear,
    },
}

@timeit
def compress_df(df, info, num=True, cat=True):

    schema = info['schema']
    if num:
        num_cols = [col for col, types in schema.items() if types == 'num']
        if len(num_cols) > 0:
            df[num_cols] = df[num_cols].astype('float32')
    if cat:
        cat_cols = [col for col, types in schema.items() if types == 'str']
        if len(cat_cols) > 0:
            df[cat_cols] = df[cat_cols].astype('category')


@timeit
def parallelize_apply(func, df, cols):
   num_threads=4
   pool = Pool(processes=num_threads)
   col_num = int(np.ceil(len(cols) / num_threads))
   res1 = pool.apply_async(func, args=(df,cols[:col_num]))
   res2 = pool.apply_async(func, args=(df,cols[col_num:2 * col_num]))
   res3 = pool.apply_async(func, args=(df,cols[2 * col_num:3 * col_num]))
   res4 = pool.apply_async(func, args=(df,cols[3 * col_num:]))
   pool.close()
   pool.join()
   df = pd.concat([df,res1.get(),res2.get(),res3.get(),res4.get()],axis=1)
   return df


@timeit
def normal_apply(func, df, cols):
    return pd.concat([df, func(df, cols)], axis=1)


@timeit
def clean_tables(df,info):
    schema = info['schema']
    num_cols = [col for col, types in schema.items() if types == 'num']
    # cat_cols = [c for c in df if c.startswith(CONSTANT.CATEGORY_PREFIX)]
    m_cat_cols = [col for col, types in schema.items() if types == 'str']
    time_cols = [col for col, types in schema.items() if types == 'timestamp']

    fillna(df,info)
    if len(m_cat_cols) > 3:
        df = parallelize_apply(count_m_cat, df, m_cat_cols)
    elif len(m_cat_cols) > 0:
        df = normal_apply(count_m_cat, df, m_cat_cols)
    if len(time_cols) > 0:
        df = normal_apply(transform_datetime, df, time_cols)
        # drop columns
    df.drop(m_cat_cols+time_cols, axis=1, inplace=True)

    #compress_df(df,info)

@timeit
def clean_df(df,info):
    #compress_df(df,info, num=False)
    #df_fillna_with_mean(df,info)
    hash_cat(df,info)
    return df

def get_dtype (df):
    for col in df:
        # get dtype for column
        dt = df[col].dtype
    return dt


@timeit
def fillna(df,info):
    schema = info['schema']
    #num_cols = [col for col, types in schema.items() if types == 'num']
    # cat_cols = [c for c in df if c.startswith(CONSTANT.CATEGORY_PREFIX)]
    m_cat_cols = [col for col, types in schema.items() if types == 'str']
    time_cols =  [col for col, types in schema.items() if types == 'timestamp']

    #for c in [num_cols]:
    #    df[c].fillna(-1, inplace=True)
    for c in [m_cat_cols]:
        df[c].fillna("0", inplace=True)
    for c in [time_cols]:
        df[c].fillna(datetime.datetime(1970, 1, 1), inplace=True)


@timeit
def df_fillna_with_mean(df,info):
    schema = info['schema']
    #for c in [col for col, types in schema.items() if types == 'num']:
    #    df[c].fillna(df[c].mean(), inplace=True)
    for c in  [col for col, types in schema.items() if types == 'timestamp']:
        mean = pd.to_timedelta(df[c]).mean() + pd.Timestamp(0)
        df[c].fillna(mean, inplace=True)
    for c in [col for col, types in schema.items() if types == 'str']:
        df[c].fillna("0", inplace=True)


@timeit
def feature_engineer(df, config):
   return df


def count_cat(df, cat_cols):
    prefix_n = CONSTANT.NUMERICAL_PREFIX
    prefix_c = CONSTANT.CATEGORY_PREFIX
    op = "frequency"
    new_df=pd.DataFrame()
    for c in cat_cols:
        dic = df[c].value_counts().to_dict()
        new_df[f"{prefix_n}{op.upper()}({c})"] = df[c].apply(lambda x: dic[x])
    return new_df

def hash_cat(df,info):
    schema = info['schema']
    for c in [col for col, types in schema.items() if types == 'str']:
        df[c] = df[c].apply(lambda x: int(x))

def frequent_cat(x):
    data = x.split(',')
    item, freq = np.unique(data, return_counts=True)
    return item[np.argmax(freq)]

def weighted_cat(dic):
    def freq(x):
        data = x.split(',')
        item, freq = np.unique(data, return_counts=True)
        global_freq = np.array([dic[i] for i in item])
        return item[np.argmax(global_freq*freq)]
    return freq

def count_m_cat(df,m_cat_cols):
    prefix_n = CONSTANT.NUMERICAL_PREFIX
    prefix_c = CONSTANT.CATEGORY_PREFIX
    op_l = 'length'
    op_f = 'frequent_cat'
    op_fw = 'frequent_weighted_cat'
    new_df=pd.DataFrame()
    for c in m_cat_cols:
        new_df[f"{prefix_c}{op_f.upper()}RANK(1)({c})"] = df[c].apply(frequent_cat)
        new_df[f"{prefix_n}{op_l.upper()}({c})"] = df[c].apply(lambda x: len(x.split(',')))
        all_item = ','.join(df[c].values).split(',')
        item, freq = np.unique(all_item, return_counts=True)
        dic = dict(zip(item, freq))
        new_df[f"{prefix_c}{op_fw.upper()}RANK(1)({c})"] = df[c].apply(weighted_cat(dic))
    return new_df


def transform_datetime(df, time_cols):
    prefix_n = CONSTANT.NUMERICAL_PREFIX
    ops = uni_ops[CONSTANT.TIME_PREFIX]
    new_dfs = []
    for c in time_cols:
        new_df = df[c].agg(ops.values())
        new_df.columns = [f"{prefix_n}{op.upper()}({c})" for op in ops]
        new_dfs += [new_df]
    return pd.concat(new_dfs, axis=1)


