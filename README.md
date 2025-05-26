/var/task/dummy_lambda.py:69: FutureWarning: Series.__getitem__ treating keys as positions is deprecated. In a future version, integer keys will always be treated as labels (consistent with DataFrame behavior). To access a value by position, use `ser.iloc[pos]`
avail = {c: r[c] for c in cols if pd.notna(r[c])}
[ERROR] 2025-05-26T13:21:01.818Z 6126f3f7-a66f-4e0d-9e97-9117fc9d5182 Unexpected error: index 1651 is out of bounds for axis 0 with size 592
Traceback (most recent call last):
 File "/var/task/dummy_lambda.py", line 114, in lambda_handler
 result = get_medication(condition, selected_column, display_mode)
 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
 File "/var/task/dummy_lambda.py", line 69, in get_medication
 avail = {c: r[c] for c in cols if pd.notna(r[c])}
 ~^^^
 File "/opt/python/pandas/core/series.py", line 1118, in __getitem__
 return self._values[key]
 ~~~~~~~~~~~~^^^^^
IndexError: index 1651 is out of bounds for axis 0 with size 592
Why I an getting this error
