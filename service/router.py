from decouple import config
from semantic_router.encoders import CohereEncoder
from semantic_router.layer import RouteLayer
from semantic_router.route import Route

from models.document import BaseDocumentChunk
from models.query import RequestPayload

from service.code_interpreter import CodeInterpreterService
from service.embedding import get_encoder
from utils.logger import logger
from utils.summarise import SUMMARY_SUFFIX
from vectordbs import BaseVectorDatabase, get_vector_service

STRUTURED_DATA = [".xlsx", ".csv", ".json"]


def create_route_layer() -> RouteLayer:
    routes = [
        Route(
            name="summarize",
            utterances=[
                "Summmarize the following",
                "Could you summarize the",
                "Summarize",
                "Provide a summary of",
            ],
            score_threshold=0.5,
        )
    ]
    cohere_api_key = config("COHERE_API_KEY", None)
    encoder = CohereEncoder(cohere_api_key=cohere_api_key) if cohere_api_key else None
    return RouteLayer(encoder=encoder, routes=routes)


async def get_documents(
    *, vector_service: BaseVectorDatabase, payload: RequestPayload
) -> list[BaseDocumentChunk]:
    chunks = await vector_service.query(input=payload.input, top_k=5)
    if not len(chunks):
        logger.error(f"No documents found for query: {payload.input}")
        return []
    is_structured = chunks[0].metadata.get("document_type") in STRUTURED_DATA
    if is_structured and payload.interpreter_mode:
        code_interpreter = CodeInterpreterService(
            session_id=payload.session_id, file_urls=[chunks[0].metadata.get("doc_url")]
        )
        code = await code_interpreter.generate_code(query=payload.input)
        async with code_interpreter as service:
            response = await service.run_python(code=code)
            output = response.stdout

    reranked_chunks = await vector_service.rerank(query=payload.input, documents=chunks)
    return reranked_chunks


async def query(payload: RequestPayload) -> list[BaseDocumentChunk]:
    rl = create_route_layer()
    decision = rl(payload.input).name
    encoder = get_encoder(encoder_config=payload.encoder)

    if decision == "summarize":
        vector_service: BaseVectorDatabase = get_vector_service(
            index_name=f"{payload.index_name}{SUMMARY_SUFFIX}",
            credentials=payload.vector_database,
            encoder=encoder,
        )
        return await get_documents(vector_service=vector_service, payload=payload)

    vector_service: BaseVectorDatabase = get_vector_service(
        index_name=payload.index_name,
        credentials=payload.vector_database,
        encoder=encoder,
    )

    return await get_documents(vector_service=vector_service, payload=payload)
