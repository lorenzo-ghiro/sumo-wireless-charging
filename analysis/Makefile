PYTHON := python
XML2CSV := $(SUMO_TOOLS)/xml/xml2csv.py
XML2PARQUET := $(SUMO_TOOLS)/xml/xml2parquet.py

SRC_DIR := ../results
XMLS := $(wildcard $(SRC_DIR)/*tripinfo*.xml)  $(wildcard $(SRC_DIR)/*battery*.xml) $(wildcard $(SRC_DIR)/*chargingstations*.xml)
CSVS := $(XMLS:.xml=.csv)
PARQS := $(XMLS:.xml=.parquet)

.PHONY: all clean
.SUFFIXES:
.DELETE_ON_ERROR:

all: $(PARQS)

$(SRC_DIR)/%.parquet: $(SRC_DIR)/%.xml
	@mkdir -p $(dir $@)
	$(PYTHON) $(XML2PARQUET) "$<" > "$@"

clean:
	@rm -f $(PARQS)
