workgroup_names = {
  investigation = "clothes-query-dev-investigation"
  detection     = "clothes-query-dev-detection"
}
results_prefixes = {
  investigation = "athena-results/investigation/"
  detection     = "athena-results/detection/"
}
bytes_scanned_cutoff_per_query = 1073741824
# Add only confirmed history prefixes after the writer contract is supplied.
detection_write_prefixes = []
