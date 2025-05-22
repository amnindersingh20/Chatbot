openapi: 3.0.1
info:
  title: MedicationLookup
  version: 1.0.0

paths:
  /medications:
    post:
      operationId: lookupMedications
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                condition:
                  type: string
                display_mode:
                  type: string
                selected_column:
                  type: string
              required:
                - condition
      responses:
        "200":
          description: successful lookup
          content:
            application/json:
              schema:
                type: object
        "404":
          description: no records found
