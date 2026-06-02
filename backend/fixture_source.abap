REPORT z_atc_s4_readiness_ecc_fixture.

*-----------------------------------------------------------------------
* Purpose:
*   Intentionally ECC-style ABAP for testing ATC S4HANA_READINESS.
*
* Usage:
*   1. Create this as a Z report in S/4HANA private cloud.
*   2. Activate it.
*   3. Run ATC with check variant S4HANA_READINESS.
*
* Important:
*   This is NOT production code.
*   Leave P_EXEC blank. The static ATC scan does not require execution.
*-----------------------------------------------------------------------

* ECC-era include for SD document category constants.
* Expected S/4 readiness area: VBTYP / RVVBTYP simplified-object usage.
INCLUDE rvvbtyp.

PARAMETERS p_exec AS CHECKBOX DEFAULT ' '.

TYPES: BEGIN OF ty_t002t,
         spras TYPE t002t-spras,
         sprsl TYPE t002t-sprsl,
         sptxt TYPE t002t-sptxt,
       END OF ty_t002t.

TYPES: BEGIN OF ty_t001,
         bukrs TYPE t001-bukrs,
         butxt TYPE t001-butxt,
       END OF ty_t001.

TYPES: BEGIN OF ty_bukrs,
         bukrs TYPE t001-bukrs,
       END OF ty_bukrs.

START-OF-SELECTION.

  WRITE: / 'ATC fixture only: intentionally ECC-style and non-compliant.'.
  WRITE: / 'Activate and run ATC with S4HANA_READINESS.'.
  WRITE: / 'Leave P_EXEC blank; execution is not needed for static ATC.'.

  IF p_exec = 'X'.
    PERFORM field_length_extension.
    PERFORM simplified_db_operations.
    PERFORM vbtyp_length_issue.
    PERFORM hana_order_dependency.
    PERFORM old_customer_vendor_tables.
    PERFORM old_transactions.
  ENDIF.

*-----------------------------------------------------------------------
* Field Length Extension examples:
* - MATNR old 18-character handling
* - old packed amount handling
*-----------------------------------------------------------------------
FORM field_length_extension.

  DATA lv_matnr_ecc18 TYPE c LENGTH 18.
  DATA lv_amount_old  TYPE p LENGTH 8 DECIMALS 2.

  SELECT matnr
    FROM mara
    INTO lv_matnr_ecc18
    UP TO 1 ROWS.
  ENDSELECT.

  SELECT dmbtr
    FROM bseg
    INTO lv_amount_old
    UP TO 1 ROWS.
  ENDSELECT.

  WRITE: / 'FLE demo:', lv_matnr_ecc18, lv_amount_old.

ENDFORM.

*-----------------------------------------------------------------------
* Simplified / replaced ECC data model direct database access.
* These are deliberately direct SELECTs on classic ECC objects.
*-----------------------------------------------------------------------
FORM simplified_db_operations.

  DATA lt_vbfa TYPE STANDARD TABLE OF vbfa.
  DATA lt_vbuk TYPE STANDARD TABLE OF vbuk.
  DATA lt_vbup TYPE STANDARD TABLE OF vbup.
  DATA lt_konv TYPE STANDARD TABLE OF konv.
  DATA lt_bseg TYPE STANDARD TABLE OF bseg.
  DATA lt_mseg TYPE STANDARD TABLE OF mseg.
  DATA lt_mkpf TYPE STANDARD TABLE OF mkpf.

  SELECT * FROM vbfa INTO TABLE lt_vbfa UP TO 1 ROWS.
  SELECT * FROM vbuk INTO TABLE lt_vbuk UP TO 1 ROWS.
  SELECT * FROM vbup INTO TABLE lt_vbup UP TO 1 ROWS.
  SELECT * FROM konv INTO TABLE lt_konv UP TO 1 ROWS.
  SELECT * FROM bseg INTO TABLE lt_bseg UP TO 1 ROWS.

  "Additional ECC-era logistics data model examples.
  SELECT * FROM mseg INTO TABLE lt_mseg UP TO 1 ROWS.
  SELECT * FROM mkpf INTO TABLE lt_mkpf UP TO 1 ROWS.

  WRITE: / 'Simplified DB operation demo executed.'.

ENDFORM.

*-----------------------------------------------------------------------
* VBTYP length / SD document category example.
* ECC code often treated VBTYP as CHAR1.
*-----------------------------------------------------------------------
FORM vbtyp_length_issue.

  DATA lv_vbtyp_ecc1 TYPE c LENGTH 1.

  SELECT vbtyp
    FROM vbrk
    INTO lv_vbtyp_ecc1
    UP TO 1 ROWS.
  ENDSELECT.

  WRITE: / 'Old VBTYP CHAR1 demo:', lv_vbtyp_ecc1.

ENDFORM.

*-----------------------------------------------------------------------
* HANA / S/4 problematic statement examples:
* - SELECT without ORDER BY followed by order-dependent operations
* - BINARY SEARCH without explicit SORT
* - DELETE ADJACENT DUPLICATES without explicit SORT
* - SELECT SINGLE with incomplete key
* - FOR ALL ENTRIES without empty-table guard
* - OPEN CURSOR without ORDER BY
*-----------------------------------------------------------------------
FORM hana_order_dependency.

  DATA lt_t002t       TYPE STANDARD TABLE OF ty_t002t.
  DATA ls_t002t       TYPE ty_t002t.
  DATA lt_bukrs       TYPE STANDARD TABLE OF ty_bukrs.
  DATA lt_t001_fae    TYPE STANDARD TABLE OF ty_t001.
  DATA lt_t001_cursor TYPE STANDARD TABLE OF ty_t001.
  DATA lv_cursor      TYPE cursor.

  "No ORDER BY, then BINARY SEARCH: intentionally order-dependent.
  SELECT spras sprsl sptxt
    FROM t002t
    INTO TABLE lt_t002t
    WHERE spras = sy-langu.

  READ TABLE lt_t002t
    INTO ls_t002t
    WITH KEY sprsl = sy-langu
    BINARY SEARCH.

  "No SORT before DELETE ADJACENT DUPLICATES.
  DELETE ADJACENT DUPLICATES FROM lt_t002t COMPARING spras.

  "Incomplete key on T002T; classic ECC style.
  SELECT SINGLE spras sprsl sptxt
    FROM t002t
    INTO ls_t002t
    WHERE spras = sy-langu.

  "FOR ALL ENTRIES without IF lt_bukrs IS NOT INITIAL.
  SELECT bukrs butxt
    FROM t001
    INTO TABLE lt_t001_fae
    FOR ALL ENTRIES IN lt_bukrs
    WHERE bukrs = lt_bukrs-bukrs.

  "OPEN CURSOR without ORDER BY.
  OPEN CURSOR WITH HOLD lv_cursor FOR
    SELECT bukrs butxt FROM t001.

  FETCH NEXT CURSOR lv_cursor
    INTO TABLE lt_t001_cursor
    PACKAGE SIZE 10.

  CLOSE CURSOR lv_cursor.

  WRITE: / 'Order dependency demo:', ls_t002t-sptxt.

ENDFORM.

*-----------------------------------------------------------------------
* Customer/Vendor master direct access.
* S/4HANA Business Partner simplification checks often flag ECC-style
* direct usage around KNA1/LFA1 depending on release/content.
*-----------------------------------------------------------------------
FORM old_customer_vendor_tables.

  DATA lt_kna1 TYPE STANDARD TABLE OF kna1.
  DATA lt_lfa1 TYPE STANDARD TABLE OF lfa1.

  SELECT * FROM kna1 INTO TABLE lt_kna1 UP TO 1 ROWS.
  SELECT * FROM lfa1 INTO TABLE lt_lfa1 UP TO 1 ROWS.

  WRITE: / 'Old customer/vendor master table demo executed.'.

ENDFORM.

*-----------------------------------------------------------------------
* Obsolete / replaced ECC transaction code literals.
* Guarded so they do not run even if P_EXEC = X.
*-----------------------------------------------------------------------
FORM old_transactions.

  IF p_exec = 'T'.  "Deliberately never true for checkbox input.

    "Customer / vendor master maintenance before Business Partner approach.
    CALL TRANSACTION 'XD01' AND SKIP FIRST SCREEN.
    CALL TRANSACTION 'XD02' AND SKIP FIRST SCREEN.
    CALL TRANSACTION 'FD01' AND SKIP FIRST SCREEN.
    CALL TRANSACTION 'FK01' AND SKIP FIRST SCREEN.

    "Classic inventory management transactions.
    CALL TRANSACTION 'MB01' AND SKIP FIRST SCREEN.
    CALL TRANSACTION 'MB1A' AND SKIP FIRST SCREEN.
    CALL TRANSACTION 'MB1B' AND SKIP FIRST SCREEN.
    CALL TRANSACTION 'MB1C' AND SKIP FIRST SCREEN.

  ENDIF.

ENDFORM.