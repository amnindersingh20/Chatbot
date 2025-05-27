RESPONSE_COLUMNS = [
           col for col in df.columns
           if col not in ("Data Point Name", "Option ID")
       ]
       logger.info("Dynamically determined RESPONSE_COLUMNS: %s", RESPONSE_COLUMNS)
   except Exception as e:
