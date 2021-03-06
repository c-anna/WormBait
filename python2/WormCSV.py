import csv
import requests
import json
import sys

"""The WormCSV module holds classes that make up the infrastructure of the data layer in WormBait

All classes in this module are used, in one way or another, to manipulate the data that makes
up the core of the WormBait run. There is a class for each of reading input data (from the
CuffLink database file), collecting data (from the WormBase RESTful API), and writing data
(to the desired output CSV file).

Christopher Anna, 2/18/2016
"""

class CuffLinkDatabase ():
    """ An object representing the data in a CuffLink output file"""

    def __init__ (self, file):
        """Constructs a CuffLinkDatabase object.

        The constructor reads a CSV file containing the results of a CuffLinks
        run. The csv library is used to quickly and efficiently turn these
        results into a dicionary. It is extremely important that headers
        are the first row of this file!

        Arguments:
        file -- the CSV file from which to read data
        """
        
        self.CSVFile = file
        self.data = {}

        reader = csv.reader(self.CSVFile, delimiter = ',', quotechar='"')

        headers = reader.next()
        
        for row in reader:
            self.data[row[0]] = dict(zip(headers,row))

    def get (self, dbId):
        """Returns all the data corresponding to a single row in the CuffLink DB file. Returns a dict of this information"""
        if dbId in self.data:
            return self.data[dbId]
        else:
            return None

    def getAll (self):
        """Returns ALL the data stored in the CuffLink DB file. Use with caution!"""
        return self.data


class OutputCSV ():
    """An object representing the output file.

    This object will perform the writing of data collected during
    the run of WormBait.

    """
    def __init__ (self, path, headers):
        """Constructs an output CSV file.

        This constructor builds the object representing a CSV output. It
        creates a new file at the specified path and writes all of the
        data collected during the WormBait run in CSV format.

        Arguments
        path -- the desired filepath for the output
        headers -- the title of each column. Not strictly necessary but makes output more accessible
        """
        self.path = path
        self.headers = headers

    def write (self, listOfWormDatas):
        """Writes all the data in argument `listOfWormDatas` to the file"""

        exclusivelyWBIds = True
        for w in listOfWormDatas:
            if exclusivelyWBIds and w.describe() and 'db_id' in w.describe() and w.describe()['db_id'].startswith('XLOC'):
                exclusivelyWBIds = False

        if exclusivelyWBIds:
            self.headers.remove('db_id')
            self.headers.remove('up/down')

        # This method requires a little kludgy glue to work on both Python2
        # and Python3. On v2, the file should be opened in binary write mode
        # On v3, this will cause exceptions. Unfortunately the 2to3 program
        # doesn't pick up on this, so I make the fix here
        if sys.version_info >= (3,0,0):
           with open(self.path, 'w') as file:
                writer = csv.DictWriter(file, fieldnames=self.headers)
                writer.writeheader()
                for wormData in listOfWormDatas:
                    writer.writerow(wormData.describe())
        else:
            with open(self.path, 'wb') as file:
                writer = csv.DictWriter(file, fieldnames=self.headers)
                writer.writeheader()
                for wormData in listOfWormDatas:
                    writer.writerow(wormData.describe())
        
            

class WormData ():
    """An object representing a gene and its associated properties.

    This class holds all the information collected from WormBase, as
    well as the low-level methods for collecting it. One WormData
    object is created for each XLOC ID specified in the input area,
    and they are populated one-by-one during the run. Finally, the
    OutputCSV class writes the data to the desired output file.
    """
    headers = {'Content-Type':'application/json'}
    """The headers needed to return usable data from the WormBase API"""

    GENE_BASE = "http://api.wormbase.org/rest/field/gene"
    """The API base URL for gene information"""
    
    PROTEIN_BASE= "http://api.wormbase.org/rest/field/protein"
    """The API base URL for protein information"""
    
    def __init__ (self, dbId, geneID, database):
        """Constructs a WormData object and kicks off the populate() method

        populate() can take up to a few seconds, since it involves making multiple
        calls to the WormBase API. Be careful about instantiating too many of these,
        at once.

        Arguments:
        xlocID -- the DB_ID parameter that corresponds to this item in the CuffLink database. This is only
        used to find CuffLink-exclusive information like the 'log2(fold_change)' value

        geneID -- the WormBase gene ID. This is the unique identifier that will allow us to collect
        information from the WormBase API

        database -- the CuffLinkDatabase object that holds the information generated by CuffLink. Used
        only for its exclusive information, like 'log2(fold_change)' 

        """
        self.geneID = geneID
        self.data = {}
        self.dbId = dbId
        self.data['gene_id'] = geneID
        self.database = database
        self.populate()

    def populate (self):
        """Populates the WormData object with all the desired data from WormBase

        Most of the data that will populate the object is captured in the various
        gene endpoints in the WormBase API. A small amount is collected from the
        protein endpoint. The data collected from WormBase is as follows:

        GENE
        sequence_name
        concise_description
        gene_models (from which protein IDs are extracted)
        gene_class
        human_orthologs
        nematode_orthologs
        other_orthologs

        PROTEIN
        best_human_match (renamed to best_human_ortholog)

        A small amount of information is collected from the CuffLink file itself.

        CUFFLINK DEG FILE
        log2(fold_change)

        For more information on the WormBase API, visit the following page:
        http://www.wormbase.org/about/userguide/for_developers/API-REST#10--10
        """

        # All WormBase genes begin with the prefix 'WBGene'. If this prefix isn't present,
        # we don't even try to collect the data
        if self.geneID and self.geneID.startswith("WBGene"):

            # Get the log2(fold_change) value for this DB_ID, straight from the
            # CuffLink database. This is the only value collected this way. Only collect
            # this value if an DB_ID has been provided.
            if self.dbId:
                self.data['up/down'] = self.database.get(self.dbId)['log2(fold_change)']

            # Most API calls will look like this. We call self.fetch and provide
            # the base URL, unique ID, and endpoint. We get the results back in
            # a JSON object and extract what we need from it
            sequence = self.fetch(self.GENE_BASE, self.geneID, 'sequence_name')
            self.data['sequence_name'] = sequence

            description = self.fetch(self.GENE_BASE, self.geneID, 'concise_description')
            self.data['description'] = description['text']

            # The gene_models endpoint will return a JSON array of proteins. We
            # must extract each protein ID and save it to the protein_id list
            # in the self.data dictionary. These protein IDs will be used
            # individually later on
            geneModels = self.fetch(self.GENE_BASE, self.geneID, 'gene_models')
            
            self.data['protein_id'] = []
            if geneModels and 'table' in geneModels:
                for item in geneModels['table']:
                    if item and 'protein' in item and 'id' in item['protein']:
                        self.data['protein_id'].append(item['protein']['id'])


            geneClass = self.fetch(self.GENE_BASE, self.geneID, 'gene_class')
            if geneClass and 'tag' in geneClass and 'label' in geneClass['tag']:
                self.data['gene_class'] = geneClass['tag']['label']

            humanOrthologs = self.fetch(self.GENE_BASE, self.geneID, 'human_orthologs')
            self.data['human_orthologs'] = []
            if humanOrthologs:
                for item in humanOrthologs:
                    self.data['human_orthologs'].append(item['ortholog']['label'])

            # For data elements that can have multiple values, we concatenate the values
            # together. The convenience method self.joinIfExtant is provided for this use
            self.joinIfExtant('human_orthologs')

            nematodeOrthologs = self.fetch(self.GENE_BASE, self.geneID, 'nematode_orthologs')
            self.data['nematode_orthologs'] = []
            if nematodeOrthologs:
                for item in nematodeOrthologs:
                    self.data['nematode_orthologs'].append(item['ortholog']['label'])

            self.joinIfExtant('nematode_orthologs')

            otherOrthologs = self.fetch(self.GENE_BASE, self.geneID, 'other_orthologs')
            self.data['other_orthologs'] = []
            if otherOrthologs:
                for item in otherOrthologs:
                    self.data['other_orthologs'].append(item['ortholog']['label'])

            self.joinIfExtant('other_orthologs')

            self.data['best_human_ortholog'] = []

            # We need to proceed differently depending on whether we have 1 protein_id
            # or many. We want to perform a request to the API for each protein_id, but
            # if we have only 1, the value self.data['protein_id'] will be a string (str)
            # and the traditional loop structure
            #
            #     for x in self.data['protein_id']
            #         ...
            #
            # will result in a loop that repeats for each character in the string self.data['protein_id']
            # So if the protein_id data is a single str, we proceed one way. If it's not, that means
            # it must be a list, and we proceed another.
            isSingular = isinstance(self.data['protein_id'], str)

            # best_human_ortholog takes no small amount of effort to extract. For
            # each protein_id collected earlier, we access that protein's endpoint
            # in the WormBase API. The information we're looking for, the description
            # of the best human ortholog is buried in several layers of JSON strata,
            # making this section hard to read at best.
            if self.data['protein_id'] and not isSingular:
                for proteinID in self.data['protein_id']:
                    bestHumanMatch = self.fetch(self.PROTEIN_BASE, proteinID, 'best_human_match')
                    if bestHumanMatch and 'description' in bestHumanMatch:
                        self.data['best_human_ortholog'].append(bestHumanMatch['description'])
            elif self.data['protein_id']:
                bestHumanMatch = self.fetch(self.PROTEIN_BASE, self.data['protein_id'], 'best_human_match')
                if bestHumanMatch and 'description' in bestHumanMatch:
                    self.data['best_human_ortholog'].append(bestHumanMatch['description'])


            self.joinIfExtant('protein_id')
            self.joinIfExtant('best_human_ortholog')

    def joinIfExtant (self, datum):
        """Convenience method that joins all values in a list with a comma, if there are values in that list

        Arguments:
        datum -- list of strings to be joined. 'datum' is used as the name because in this module, the values
        that will be passed in represent the results from one call to the WormBase API

        Return:
        a comma-separated string of all values in datum
        """
        
        if len(self.data[datum]) == 0:
            self.data[datum] = None
        else:
            self.data[datum] = ', '.join(self.data[datum])
        
    def get (self, datum):
        """Public access to the data stored in self.data

        Arguments:
        datum -- the name of the desired data. E.g., 'sequence_name', 'human_orthologs'

        Return:
        the data with the given name in self.data, if it exists. `None` if it doesn't
        """
        if datum in self.data:
            return self.data[datum]
        else:
            return None

    def describe (self):
        """Returns the entirety of self.data"""
        return self.data

    def fetch (self, baseUrl, id, datum):
        """Makes an HTTP GET request to the WormBase RESTful API

        Arguments:
        baseUrl -- the base URL of the API. In this module, could be GENE_BASE or PROTEIN_BASE
        id -- the WormBase ID of the gene or protein for lookup
        datum -- the specific endpoint that will be accessed
        """
        r = requests.get(baseUrl + '/' + id + '/' + datum, headers=self.headers)

        # We must manipulate the data in JSON format. We try to get the JSON form
        # of the response to the request. If it doesn't work, return None
        try:
            j = r.json()
        except:
            return None

        # WormBase provides a decent amount of ancillary data when returning from
        # its API. We are not interested in anything outside of the 'data' key
        # in the returned JSON object, so we extract it here. If there is no 'data'
        # in the JSON object, return None
        if datum in j and 'data' in j[datum]:
            return j[datum]['data']
        else:
            return None
        
        

    
        
