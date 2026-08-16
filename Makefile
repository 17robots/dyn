.PHONY: all test clean per-file grammar

all:
	$(MAKE) -C .. all

test:
	$(MAKE) -C .. test

per-file:
	$(MAKE) -C .. per-file

grammar:
	$(MAKE) -C .. grammar

clean:
	$(MAKE) -C .. clean
