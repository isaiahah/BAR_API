import re
from flask_restx import Namespace, Resource, fields
from flask import request
from api.utils.bar_utils import BARUtils
from marshmallow import Schema, ValidationError, fields as marshmallow_fields
from markupsafe import escape
from api import db
from api.models.single_cell import SampleData as SingleCell
from api.models.embryo import SampleData as Embryo
from api.models.shoot_apex import SampleData as ShootApex
from api.models.germination import SampleData as Germination
from api.models.silique import SampleData as Silique
from api.models.klepikova import SampleData as Klepikova
from api.models.dna_damage import SampleData as DNADamage
from sqlalchemy import and_

rnaseq_gene_expression = Namespace(
    "RNA-Seq Gene Expression",
    description="RNA-Seq Gene Expression data from the BAR Databases",
    path="/rnaseq_gene_expression",
)

# I think this is only needed for Swagger UI POST
gene_expression_request_fields = rnaseq_gene_expression.model(
    "GeneExpression",
    {
        "species": fields.String(required=True, example="arabidopsis"),
        "database": fields.String(required=True, example="single_cell"),
        "gene_id": fields.String(required=True, example="At1g01010"),
        "sample_ids": fields.List(
            example=[
                "cluster0_WT1.ExprMean",
                "cluster0_WT2.ExprMean",
                "cluster0_WT3.ExprMean",
            ],
            cls_or_instance=fields.String,
        ),
    },
)


# Validation is done in a different way to keep things simple
class RNASeqSchema(Schema):
    species = marshmallow_fields.String(required=True)
    database = marshmallow_fields.String(required=True)
    gene_id = marshmallow_fields.String(required=True)
    sample_ids = marshmallow_fields.List(cls_or_instance=marshmallow_fields.String)


class RNASeqUtils:
    @staticmethod
    def get_data(species, database, gene_id, sample_ids=None):
        """This function is used to query the database for gene expression
        :param species: name of species
        :param database: name of BAR database
        :param gene_id: gene id in the data_probeset column
        :param sample_ids: sample ids in the data_bot_id column
        :return: dict gene expression data
        """
        if sample_ids is None:
            sample_ids = []
        data = {}

        # Set species and check gene ID format
        if species == "arabidopsis":
            if not BARUtils.is_arabidopsis_gene_valid(gene_id):
                return {"success": False, "error": "Invalid gene id", "error_code": 400}
        else:
            return {"success": False, "error": "Invalid species", "error_code": 400}

        # Set model: Arabidopsis
        if database == "single_cell":
            table = SingleCell
            # Example: cluster0_WT1.ExprMean
            sample_regex = re.compile(r"^\D+\d+_WT\d+.ExprMean$", re.I)

        elif database == "embryo":
            table = Embryo
            sample_regex = re.compile(r"^\D{1,3}_\d$|Med_CTRL$", re.I)

        elif database == "shoot_apex":
            table = ShootApex
            sample_regex = re.compile(r"^\D{1,5}\d{0,2}$", re.I)

        elif database == "germination":
            table = Germination
            sample_regex = re.compile(r"^\d{1,3}\D{1,4}_\d{1,3}|harvest_\d|Med_CTRL$", re.I)

        elif database == "silique":
            table = Silique
            # Insane regex! Needs work
            sample_regex = re.compile(r"^\d{1,3}_dap.{1,58}_R1_001|Med_CTRL$", re.I)

        elif database == "klepikova":
            table = Klepikova
            sample_regex = re.compile(r"^SRR\d{1,9}|Med_CTRL$", re.I)

        elif database == "dna_damage":
            table = DNADamage
            # Another insane regex!
            sample_regex = re.compile(r"^\D{1,3}.{1,30}_plus_Y|\D{1,3}.{1,30}_minus_Y|Med_CTRL$", re.I)

        else:
            return {"success": False, "error": "Invalid database", "error_code": 400}

        # Now query the database
        # We are querying only some columns because full indexes are made on some columns, now the whole table
        if len(sample_ids) == 0 or sample_ids is None:
            rows = db.session.execute(
                db.select(table.data_probeset_id, table.data_bot_id, table.data_signal).where(
                    table.data_probeset_id == gene_id
                )
            ).all()
            for row in rows:
                data[row[1]] = row[2]

        else:
            # Validate all samples
            for sample_id in sample_ids:
                if not sample_regex.search(sample_id):
                    return {
                        "success": False,
                        "error": "Invalid sample id",
                        "error_code": 400,
                    }

            rows = db.session.execute(
                db.select(table.data_probeset_id, table.data_bot_id, table.data_signal).where(
                    and_(
                        table.data_probeset_id == gene_id,
                        table.data_bot_id.in_(sample_ids),
                    )
                )
            ).all()
            for row in rows:
                data[row[1]] = row[2]

        return {"success": True, "data": data}


@rnaseq_gene_expression.route("/")
class PostRNASeqExpression(Resource):
    @rnaseq_gene_expression.expect(gene_expression_request_fields)
    def post(self):
        """This end point returns gene expression data for a single gene and multiple samples."""
        json_data = request.get_json()

        # Validate json
        try:
            json_data = RNASeqSchema().load(json_data)
        except ValidationError as err:
            return BARUtils.error_exit(err.messages), 400

        species = json_data["species"]
        database = json_data["database"]
        gene_id = json_data["gene_id"]
        sample_ids = json_data["sample_ids"]

        results = RNASeqUtils.get_data(species, database, gene_id, sample_ids)

        if results["success"]:
            # Return results if there are data
            if len(results["data"]) > 0:
                return BARUtils.success_exit(results["data"])
            else:
                return BARUtils.error_exit("There are no data found for the given gene")
        else:
            return BARUtils.error_exit(results["error"]), results["error_code"]


@rnaseq_gene_expression.route("/<string:species>/<string:database>/<string:gene_id>")
class GetRNASeqGeneExpression(Resource):
    @rnaseq_gene_expression.param("species", _in="path", default="arabidopsis")
    @rnaseq_gene_expression.param("database", _in="path", default="single_cell")
    @rnaseq_gene_expression.param("gene_id", _in="path", default="At1g01010")
    def get(self, species="", database="", gene_id=""):
        """This end point returns RNA-Seq gene expression data"""
        # Variables
        species = escape(species)
        database = escape(database)
        gene_id = escape(gene_id)

        results = RNASeqUtils.get_data(species, database, gene_id)

        if results["success"]:
            # Return results if there are data
            if len(results["data"]) > 0:
                return BARUtils.success_exit(results["data"])
            else:
                return BARUtils.error_exit("There are no data found for the given gene")
        else:
            return BARUtils.error_exit(results["error"]), results["error_code"]


@rnaseq_gene_expression.route("/<string:species>/<string:database>/<string:gene_id>/<string:sample_id>")
class GetRNASeqGeneExpressionSample(Resource):
    @rnaseq_gene_expression.param("species", _in="path", default="arabidopsis")
    @rnaseq_gene_expression.param("database", _in="path", default="single_cell")
    @rnaseq_gene_expression.param("gene_id", _in="path", default="At1g01010")
    @rnaseq_gene_expression.param("sample_id", _in="path", default="cluster0_WT1.ExprMean")
    def get(self, species="", database="", gene_id="", sample_id=""):
        """This end point returns RNA-Seq gene expression data"""
        # Variables
        species = escape(species)
        database = escape(database)
        gene_id = escape(gene_id)
        sample_id = escape(sample_id)

        results = RNASeqUtils.get_data(species, database, gene_id, [sample_id])

        if results["success"]:
            # Return results if there are data
            if len(results["data"]) > 0:
                return BARUtils.success_exit(results["data"])
            else:
                return BARUtils.error_exit("There are no data found for the given gene")
        else:
            return BARUtils.error_exit(results["error"]), results["error_code"]
